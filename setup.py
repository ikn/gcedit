import setuptools

with open('README.md', 'r') as f:
    readme_text = f.read()

setuptools.setup(
    name='gcedit',
    version='0.4.3',
    author='Joseph Lansdowne',
    author_email='ikn@ikn.org.uk',
    description='GameCube disk editor',
    long_description=readme_text,
    long_description_content_type='text/markdown',
    url='http://ikn.org.uk/lib/gw2buildutil',
    packages=setuptools.find_packages(),
    package_data={'': ['locale/*/LC_MESSAGES/*.mo']},
    classifiers=[
        'Programming Language :: Python :: 3.2',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: OS Independent',
    ],
)
