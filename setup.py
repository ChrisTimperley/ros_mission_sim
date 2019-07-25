import os
from glob import glob
from setuptools import setup, find_packages

path = os.path.join(os.path.dirname(__file__), 'houston/version.py')
with open(path, 'r') as f:
    exec(f.read())

setup(
    name='houston',
    version=__version__,
    description='TBA',
    author='Chris Timperley, Jam M. Hernandez Q., Afsoon Afzal',
    author_email='christimperley@gmail.com, jamarck96@gmail.com, afsoona@cs.cmu.edu',
    url='https://github.com/squaresLab/Houston',
    license='mit',
    python_requires='>=3.5',
    include_package_data=True,
    install_requires = [
        'flask',
        'pytest',
        'pexpect',
        'geopy',
        'bugzoo>=2.1.24',
        'dronekit>=2.9.1',
        'pymavlink>=2.3.4',
        'attrs',
        'ruamel.yaml>=0.15.86',
        'sexpdata',
        'numpy'
    ],
    packages = [
        'houston',
        'houston.root_cause',
        'houston.generator',
        'houston.ardu',
        'houston.ardu.copter',
        'houston.ardu.rover'
    ],
    package_dir = {
        'houston': 'houston',
        'houston.generator': 'houston/generator',
        'houston.ardu': 'houston/ardu',
        'houston.ardu.common': 'houston/ardu/common',
        'houston.ardu.copter': 'houston/ardu/copter',
        'houston.ardu.rover': 'houston/ardu/rover'
    }
)
