from setuptools import setup

setup(
    name="ufork",
    version="20.11.0",
    author="Kurt Rose",
    author_email="kurt@kurtrose.com",
    description="A simple pre-forking server container.",
    license="BSD",
    url="http://github.com/kurtbrose/ufork",
    packages=['ufork'],
    long_description='A simple, pure-Python preforking server container.',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        'License :: OSI Approved :: BSD License',
    ]
)

"""
A brief checklist for release:

* tox
* git commit (if applicable)
* Bump version off dev
* git commit -a -m "bump version for vx.y.z release"
* rm -rf dist/*
* python setup.py sdist bdist_wheel
* twine upload dist/*
* bump docs/conf.py version
* git commit
* git tag -a vx.y.z -m "brief summary"
* write CHANGELOG
* git commit
* bump glom/_version.py onto n+1 dev
* git commit
* git push

"""
