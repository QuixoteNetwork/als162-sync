#!/bin/sh
set -e
cd "$(dirname "$0")/.."
sudo apt-get update
sudo apt-get install -y devscripts debhelper dh-python python3-all \
    python3-setuptools pybuild-plugin-pyproject lintian
dpkg-buildpackage -us -uc -b
ls -l ../als162-sync_*.deb
