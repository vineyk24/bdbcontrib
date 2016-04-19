# -*- coding: utf-8 -*-

#   Copyright (c) 2010-2016, MIT Probabilistic Computing Project
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from io import BytesIO
import mock
import multiprocessing
import numpy as np
import re
import os
import pandas as pd
import pytest
import random
import shutil
from string import ascii_lowercase  # pylint: disable=deprecated-module
import tempfile

import bayeslite
import bdbcontrib

from bayeslite.exception import BayesLiteException as BLE
from bayeslite.loggers import CaptureLogger
from bayeslite.read_csv import bayesdb_read_csv
from bdbcontrib.bql_utils import cursor_to_df
from bdbcontrib.plot_utils import _pairplot

def dataset(num_rows=400):
    '''Column names give rough type, numbers show which are related.'''
    df = pd.DataFrame()
    alphabet = ['A', 'B', 'C', 'D', 'E']
    dist_of_five = np.random.choice(range(5), num_rows,
                                    p=np.array([1, .4, .3, .2, .1]) / 2.)
    df['floats_1'] = [np.random.randn() + x for x in dist_of_five]
    df['categorical_1'] = [alphabet[i] for i in dist_of_five]

    dist_of_five = np.random.choice(range(5), num_rows,
                                    p=np.array([1, .4, .3, .2, .1]) / 2.)
    df['categorical_2'] = [alphabet[i] for i in dist_of_five]

    few_ints = np.random.choice(range(4), num_rows, p=[.4, .3, .2, .1])
    df['few_ints_3'] = few_ints
    df['floats_3'] = [(np.random.randn() - 2 * x) / (1 + x) for x in few_ints]

    df['many_ints_4'] = np.random.randn(num_rows)

    # Need >= 75% to be zero to trigger inter-quartile-range == 0.
    numeric_5 = np.random.choice(
        range(4), num_rows, p=[200./256, 40./256, 10./256, 6./256])
    # Need >= 30 unique to be numeric instead of categorical,
    # so perturb the non-zeros:
    df['skewed_numeric_5'] = [ i * np.random.random() for i in numeric_5 ]
    csv_data = BytesIO()
    df.to_csv(csv_data, header=True, index_label='index')
    return (df, csv_data)

def ensure_timeout(delay, target):
    proc = multiprocessing.Process(target=target)
    proc.start()
    proc.join(delay)
    assert not proc.is_alive()

# Session scope (entire test run) rather than module scope (this test) because
# it will be re-used by other test files testing other modules:
@pytest.fixture(scope='session')
def dts_df(request):
    (df, csv_data) = dataset(40)
    tempd = tempfile.mkdtemp(prefix="bdbcontrib-test-recipes")
    request.addfinalizer(lambda: shutil.rmtree(tempd))
    csv_path = os.path.join(tempd, "data.csv")
    with open(csv_path, "w") as csv_f:
        csv_f.write(csv_data.getvalue())
    bdb_path = os.path.join(tempd, "data.bdb")
    name = ''.join(random.choice(ascii_lowercase) for _ in range(32))
    dts = bdbcontrib.quickstart(name=name, csv_path=csv_path, bdb_path=bdb_path,
        logger=CaptureLogger(verbose=pytest.config.option.verbose),
        session_capture_name="test_recipes.py")
    ensure_timeout(10, lambda: dts.analyze(models=10, iterations=20))
    return dts, df

def prepare():
    (df, csv_str) = dataset()
    os.environ['BAYESDB_WIZARD_MODE']='1'
    bdb = bayeslite.bayesdb_open()
    # XXX Do we not have a bayesdb_read_df ?
    bayesdb_read_csv(bdb, 'plottest', flush(csv_str),
                     header=True, create=True)
    bdb.execute('''
        create generator plottest_cc for plottest using crosscat(guess(*))
    ''')

    # do a plot where a some sub-violins are removed
    _remove_violin_bql = """
        DELETE FROM plottest
            WHERE categorical_1 = "B"
                AND (few_ints_3 = 2 OR few_ints_3 = 1);
    """
    cursor = bdb.execute('SELECT * FROM plottest')
    df = cursor_to_df(cursor)
    return (df, bdb)

def do(prepped, location, **kwargs):
    (df, bdb) = prepped
    plt.figure(tight_layout=True, facecolor='white')
    _pairplot(df, bdb=bdb, generator_name='plottest_cc',
              show_full=False, **kwargs)
    plt.savefig(location)

def run_histogram(bdb, df, location, **kwargs):
    plt.figure(tight_layout=True, facecolor='white')
    bdbcontrib.plot_utils.histogram(bdb, df)
    plt.savefig(location)

from PIL import Image
def has_nontrivial_contents_over_white_background(imgfile):
    img = Image.open(imgfile)
    pix = img.load()
    hist = img.histogram()
    # White background means corners are likely white:
    assert pix[0, 0] == (255, 255, 255, 255)
    assert pix[img.size[0] - 1, img.size[1] - 1] == (255, 255, 255, 255)
    white = hist[-1]
    total = sum(hist)
    # Total white should be between 10 and 90% of the image.
    assert total * .1 < white
    assert white < total * .9
    # Total number of different intensities used should be between 10 and 90%
    # of the available intensities.
    zeros = len([intensity for intensity in hist if intensity == 0])
    assert len(hist) * .1 < zeros
    assert zeros < len(hist) * .9
    return True

def flush(f):
    return BytesIO(f.getvalue())

def test_pairplot_smoke():
    ans = prepare()
    f = BytesIO()
    do(ans, f, colorby='categorical_2', show_contour=False)
    assert has_nontrivial_contents_over_white_background(flush(f))
    f = BytesIO()
    do(ans, f, colorby='categorical_2', show_contour=True)
    assert has_nontrivial_contents_over_white_background(flush(f))
    f = BytesIO()
    do(ans, f, show_contour=False)
    assert has_nontrivial_contents_over_white_background(flush(f))

def test_one_variable():
    (df, bdb) = prepare()
    for var in ['categorical_1', 'few_ints_3', 'floats_3', 'many_ints_4',
                'skewed_numeric_5']:
      cursor = bdb.execute('SELECT %s FROM plottest' % (var,))
      df = cursor_to_df(cursor)
      f = BytesIO()
      do((df, bdb), f, show_contour=False)
      assert has_nontrivial_contents_over_white_background(flush(f))
      cursor = bdb.execute('SELECT %s, categorical_2 FROM plottest' % (var,))
      df = cursor_to_df(cursor)
      f = BytesIO()
      do((df, bdb), f, colorby='categorical_2', show_contour=False)
      assert has_nontrivial_contents_over_white_background(flush(f))
      f = BytesIO()
      do((df, bdb), f, colorby='categorical_2', show_contour=True)
      assert has_nontrivial_contents_over_white_background(flush(f))

def test_heatmap(dts_df):
    dts, _df = dts_df
    plot = dts.heatmap('ESTIMATE DEPENDENCE PROBABILITY'
                       ' FROM PAIRWISE COLUMNS OF %g'
                       ' WHERE name0 LIKE "categorical%"')
    f = BytesIO()
    plot.savefig(f)
    assert has_nontrivial_contents_over_white_background(flush(f))

def test_histogram():
    categoricals = set(['categorical_1', 'categorical_2', 'few_ints_3'])
    numerics = set(['floats_1', 'floats_3', 'many_ints_4', 'skewed_numeric_5'])
    (df, bdb) = prepare()
    f = BytesIO()
    with pytest.raises(BLE):
        run_histogram(bdb, pd.DataFrame(), f)
    with pytest.raises(BLE):
        run_histogram(bdb, df[['categorical_1', 'few_ints_3', 'floats_3']], f)
    for datacol in categoricals:
        with pytest.raises(BLE):
            run_histogram(bdb, df[[datacol]], f)
        with pytest.raises(BLE):
            run_histogram(bdb, df[[datacol, 'categorical_1']], f)
        with pytest.raises(BLE):
            run_histogram(bdb, df[[datacol, 'many_ints_4']], f)
    for colorby in numerics:
        with pytest.raises(BLE):
            run_histogram(bdb, df[['many_ints_4', colorby]], f)

    for datacol in numerics:
        for colorby in categoricals:
            f = BytesIO()
            run_histogram(bdb, df[[datacol]], f)
            assert has_nontrivial_contents_over_white_background(flush(f))
            if datacol == colorby:
                with pytest.raises(BLE):
                    f = BytesIO()
                    run_histogram(bdb, df[[datacol, colorby]], f)
            else:
                f = BytesIO()
                run_histogram(bdb, df[[datacol, colorby]], f)
                assert has_nontrivial_contents_over_white_background(flush(f))

def get_plot_text(obj):
    texts = []
    stack = [obj]
    while stack:
        item = stack.pop()
        d = set(dir(item))
        if 'get_children' in d:
            stack += item.get_children()
        if 'get_text' in d:
            texts.append(item.get_text())
    return texts

def test_gen_collapsed_legend_from_dict():
    hl_colors_dict = {'roses': 'red',
                      'violets': 'blue',
                      'lilies': 'white',
                      'poppies': 'red'}
    # http://matplotlib.org/api/pyplot_api.html#matplotlib.pyplot.legend
    loc = 10  # center
    title = 'Doggerel!'
    fontsize = 'medium'
    leg = bdbcontrib.plot_utils.gen_collapsed_legend_from_dict(
        hl_colors_dict, loc, title, fontsize)
    texts = get_plot_text(leg)
    assert 'Doggerel!' in texts
    assert 'violets' in texts
    assert 'lilies' in texts
    assert ('roses, poppies' in texts or 'poppies, roses' in texts)


def main():
    ans = prepare()
    do(ans, 'fig0.png', colorby='categorical_2', show_contour=False)
    do(ans, 'fig1.png', colorby='categorical_2', show_contour=True)
    do(ans, 'fig2.png', show_contour=False)
    print "Figures saved in 'fig0.png', 'fig1.png', 'fig2.png'"
    assert os.path.exists('fig0.png')
    assert os.path.exists('fig1.png')
    assert os.path.exists('fig2.png')

if __name__ == '__main__':
    main()
