#!/usr/bin/env python

from distutils.core import setup

from setuptools import find_packages

setup(
    name='bitcointools',
    version='0.1',
    description='Bitcoin tools utility',
    author='GavinAndresen',
    author_email='<gavinandresen@gmail.com>',
    maintainer='Shiva S',
    maintainer_email='<shivaenigma@gmail.com>',
    url='https://github.com/shivaenigma/bitcointools',
    packages=find_packages(),
    classifiers=[
        'License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)', 'Operating System :: OS Independent'
    ]
)
