from __future__ import absolute_import
from __future__ import unicode_literals

import os
import sys

from setuptools import setup


# Package meta-data.
NAME = 'syncopath'
DESCRIPTION = 'Synchronize the contents from one directory to another.'
URL = 'https://github.com/kurtmckee/syncopath'
EMAIL = 'contactme@kurtmckee.org'
AUTHOR = 'Kurt McKee'

# What packages are required for this module to be executed?
REQUIRED = []
if sys.version_info[:2] < (3, 5):
    REQUIRED.append('scandir')

here = os.path.abspath(os.path.dirname(__file__))

# Load the package's __version__.py module as a dictionary.
about = {}
with open(os.path.join(here, NAME, '__version__.py'), 'rb') as f:
    blob = f.read().decode('utf-8')

VERSION = blob.split('=', 1)[-1].strip().strip('\'"')

setup(
    name=NAME,
    version=VERSION,
    description=DESCRIPTION,
    author=AUTHOR,
    author_email=EMAIL,
    url='https://github.com/kurtmckee/syncopath',
    packages=[NAME],

    install_requires=REQUIRED,
    include_package_data=True,
    license='GPLv3',
    classifiers=[
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: Implementation :: CPython',
    ],
)
