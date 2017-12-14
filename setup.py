from __future__ import absolute_import
from __future__ import unicode_literals

from setuptools import find_packages, setup, Command

import syncopath

setup(
    name='syncopath',
    version=syncopath.__version__,
    description='Synchronize the contents from one directory to another.',
    author='Kurt McKee',
    author_email='contactme@kurtmckee.org',
    url='https://github.com/kurtmckee/syncopath',
    packages=['syncopath'],

    install_requires=['scandir'],
    include_package_data=True,
    license='MIT',
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: Implementation :: CPython',
    ],
)
