Installing new versions of kadi or other apps to the production server

Local Testing
--------------
Initial setup
^^^^^^^^^^^^^^
::

  WEB_KADI=/proj/web-kadi

Option 1
~~~~~~~~~
This is preferred over option 2::

  ska # get into Ska environment

  TEST_PREFIX=$HOME/tmp/web-kadi  # or wherever
  mkdir -p $TEST_PREFIX/lib/python2.7/site-packages
  export PYTHONPATH=$TEST_PREFIX/lib/python2.7/site-packages:$WEB_KADI/lib/python2.7/site-packages

  cd ~/git/kadi
  cp ./manage.py ~/tmp

Then install local test versions of kadi and/or mica as shown below.

Option 2
~~~~~~~~~
This has not been tested::

  # Activate and update a root dev ska to be synced with flight
  conda install --file=pkgs.conda
  make python_modules

  # Clone it into a new environment.  This also clones pip-installed packages.
  conda create -n test-web-kadi --clone root
  source activate test-web-kadi

  TEST_PREFIX=`python -c 'import sys; print(sys.prefix)'`
  export PYTHONPATH=$WEB_KADI/lib/python2.7/site-packages

  cd ~/git/kadi
  cp ./manage.py ~/tmp


Kadi
^^^^
The ``--prefix`` is not strictly required for option 2, but it should not hurt anything.

::

  cd ~/git/kadi
  git branch  # confirm correct web branch
  git status  # confirm no stray modifications
  rm -rf build
  rm -rf $TEST_PREFIX/lib/python2.7/site-packages/kadi*
  python setup.py install --prefix=$TEST_PREFIX

Mica
^^^^^
::

  cd ~/git/mica
  git branch  # confirm correct web branch
  git status  # confirm no stray modifications
  rm -rf build
  rm -rf $TEST_PREFIX/lib/python2.7/site-packages/mica*
  python setup.py install --prefix=$TEST_PREFIX

Run server and test
^^^^^^^^^^^^^^^^^^^^
::

  cd ~/tmp
  ./manage.py runserver
  # Check it out.
  # Look also at admin site: http://127.0.0.1:8000/admin

Production installation
-----------------------
Basic setup::

  ska  # Enter ska flight environment on HEAD

  # Local (Apache) PREFIX and PYTHONPATH for web application packages.
  # Note that there is no Python installed at PREFIX.
  export PYTHONPATH=${WEB_KADI}/lib/python2.7/site-packages

Kadi
^^^^^
As needed::

  cd ~/git/kadi
  git branch  # confirm correct web branch
  git status  # confirm no stray modifications

  # Remove project and kadi.events app if needed
  ls -ld $PYTHONPATH/kadi*
  rm -rf $PYTHONPATH/kadi*.egg-info
  rf -rf $PYTHONPATH/kadi-bak

  # fast
  mv $PYTHONPATH/kadi{,-bak}
  python setup.py install --prefix=$WEB_KADI

  ls -ld $PYTHONPATH/kadi*

Restart::

  sudo /etc/rc.d/init.d/httpd-kadi restart
  # Check it out  http://kadi.cfa.harvard.edu
  # Look also at admin site: http://kadi.cfa.harvard.edu/admin

Mica
^^^^^
As needed::

  cd ~/git/mica
  git branch  # confirm correct web branch
  git status  # confirm no stray modifications

  ls -ld $PYTHONPATH/mica*
  rm -rf $PYTHONPATH/mica*
  python setup.py install --prefix=$WEB_KADI


