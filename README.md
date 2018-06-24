# man2qhelp

Allows conversion of a whole man category to a Qt Help Project file that can then be compiled to a .qch help file.
For example, to create project containing man2, run

    ./man2qhelp.py 2
    qhelpgenerator man.qhp

to first create `man.qhp` and then to convert it to `man.qch`. Then open Qt Creator settings about Help and add the
file to registered documentation. Now the man2 category pages can be accessed from Qt Creator help.

## Requirements

- python 3.6 (at least),
- groff 1.22 (but may work on other versions too),
- netpbm 10.70 (or such, required by groffhtml driver),
- psutils 1.17 (or such, required by groffhtml driver),
- qthelp 5.9 (or such).

## Known problems / limitations

- groffhtml converts tables to images instead of using `<table>` element.
- Caching does not work yet correctly. Using `-f` argument for the script may be required.
- Cross-references are not checked and the resulting link may be broken.
- Converting only single page, multiple categories, or combination of those is not tested.
- Output filename is hard-coded and filtering or help options cannot be changed.
