from distutils.core import setup

setup(
    name='PewPew',
    version='0.1',
    author='Odd Rune Lykkebø',
    author_email='oddrunesl@gmail.com',
    packages=['pewpew'],
    scripts=['bin/launch.sh'],
    license='LICENSE.txt',
    description='A silly game.',
    long_description=open('README.txt').read(),
    install_requires=[
        'pygame', 
        'numpy',
        'pygame_menu'
        'pillow'
    ],
)
