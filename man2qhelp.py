#!/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2018 Jyrki Launonen

import argparse
from collections import OrderedDict
import glob
import os.path
import re
import subprocess
import sys
from html.parser import HTMLParser
from typing import Callable, List, NamedTuple, Optional, Tuple


__version__ = "0.2"

DEFAULT_NAMESPACE = "man.linux.org.1.0"
IN_PATH = "/usr/share/man/man%s"
MAN_LINK = re.compile(r"<b>(\w+)</b>\((\d+p?)\)")
IMAGE_NAME_RE = re.compile(r"(?P<keyword>.+?)-\d+\.\w+")
QHP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<QtHelpProject version="1.0">
<namespace>{namespace}</namespace>
<virtualFolder>man-pages</virtualFolder>
<customFilter name="Linux Man 1.0">
    <filterAttribute>man</filterAttribute>
</customFilter>
""", """</QtHelpProject>
"""
CATEGORY_TEMPLATE = """<filterSection>
    <filterAttribute>man</filterAttribute>
    <filterAttribute>{filter_category}</filterAttribute>
    <keywords>
""", """\
    </keywords>
    <files>
""", """\
    </files>
</filterSection>
"""


class BasePath(object):
    def __init__(self, path: str):
        self._path = path

    def join(self, *paths: str) -> str:
        return os.path.join(self._path, *paths)


Options = NamedTuple("Options", [
    ("cache_path", BasePath),
    ("qhp", str),
    ("force", bool),
    ("sources", List[str]),
    ("qhp_namespace", str),
    ("quiet", bool),
    ("print", Callable)
])

LevelResult = NamedTuple("LevelResult", [
    ("keywords", List["Keyword"]),
    ("cross_references", List[Tuple[str, str]]),
    ("has_errors", bool),
])


def man_path(level: int, page: Optional[str]=None) -> str:
    if page is None:
        return IN_PATH % level
    return os.path.join(IN_PATH % level, page)


def src_bzip(path: str) -> str:
    return subprocess.check_output(["bunzip2", "-c", path]).decode("utf-8", errors="replace")


def src_gzip(path: str) -> str:
    return subprocess.check_output(["gunzip", "-c", path]).decode("utf-8", errors="replace")


def src_raw(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def remove_extensions(source: str, *extensions: str) -> str:
    base, ext = os.path.splitext(source)
    if ext in extensions:
        return remove_extensions(base, *extensions)
    return source


def result_name(source_name: str, level: str) -> str:
    stripped = remove_extensions(os.path.basename(source_name), ".bz2", "." + level)
    return stripped + ".html"


def src(path: str) -> Optional[Tuple[Optional[str], str, Optional[str]]]:
    if not os.path.exists(path):
        print("Does not exist:", path)
        return None

    base = os.path.basename(path)
    if path.endswith(".bz2"):
        data = src_bzip(path)
        name = os.path.splitext(base)[0]
    elif path.endswith(".gz"):
        data = src_gzip(path)
        name = os.path.splitext(base)[0]
    else:
        data = src_raw(path)
        name = base
    name = os.path.splitext(name)[0]

    if data.startswith(".so "):
        alias = data.strip().split("\n")
        if len(alias) == 1:
            alias = alias[0]
            alias_info = re.match(r"\.so\s+(?:.*?/)?man(\d+)/([\w_-]+)", alias)
            if alias_info is not None:
                alias_path = man_path(int(alias_info.group(1)), alias_info.group(2))
            else:
                alias_info = re.match(r"\.so\s+([\w_-]+\.(\d))", alias)
                if alias_info is not None:
                    alias_path = man_path(int(alias_info.group(2)), alias_info.group(1))
                else:
                    print("not understood alias:", name, data)
                    return None

            candidates = glob.glob(alias_path + ".*")
            if len(candidates) == 0:
                print("No matching alias source:", alias_path)
                return None

            elif len(candidates) > 1:
                print("Too many candidates:", name, "/", alias)
                print("\n".join(candidates))
                return None

            else:
                return None, name, candidates[0]
    else:
        return data, name, None


class TitleFinder(HTMLParser):
    def __init__(self):
        super(TitleFinder, self).__init__()
        self._in_title = False
        self._title = ""

    @property
    def title(self):
        return self._title

    def error(self, message):
        print(message)

    def handle_starttag(self, tag, attrs):
        if tag == "title" and not self._in_title:
            if len(self._title) == 0:
                self._in_title = True
            else:
                print("Multiple title-elements")
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
        super().handle_endtag(tag)

    def handle_data(self, data):
        if self._in_title:
            self._title += data
        super().handle_data(data)


def title_tag(text: str) -> str:
    return "<title>" + text + "</title>"


class Keyword(object):
    def __init__(self, keyword: str, target: str, is_alias: bool = False):
        self.keyword = keyword
        "Keyword, such as `select`."

        self.target = target
        "Output or target filename."

        self.is_alias = is_alias
        "If `True`, `target` points to the alias target."


def link_replacer(ref_list: List[Tuple[str, str]]):
    def fn(match) -> str:
        name = match.group(1)
        level = match.group(2)
        ref_list.append((level, name))
        return '<a href="../html.' + level + '/' + name + '.html">' + match.group(0) + '</a>'
    return fn


def do_level(level: str, options: Options) -> LevelResult:
    level_keywords = []  # type: List[Keyword]
    cross_references = []  # type: List[Tuple[str, str]]
    has_errors = False

    out_dir = options.cache_path.join("html.%s" % level)
    if not os.path.exists(out_dir):
        os.mkdir(out_dir)
    images_dir = os.path.join(out_dir, "images")
    if not os.path.exists(images_dir):
        os.mkdir(images_dir)
    in_dir = IN_PATH % level

    # Needed for images to work correctly with relative path.
    original_dir = os.getcwd()
    os.chdir(out_dir)

    for f in os.listdir(in_dir):
        source_filename = os.path.join(in_dir, f)
        source_mtime = os.path.getmtime(source_filename)

        src_result = src(source_filename)
        if src_result is None:
            continue
        man_data, name, alias = src_result

        if man_data is None:
            base_name = result_name(alias, level)
            target = options.cache_path.join("html.%s" % level, base_name)
            options.print("alias", name, "=", target)
            level_keywords.append(Keyword(name, target, is_alias=True))
            continue

        base_name = result_name(name, level)
        target = options.cache_path.join("html.%s" % level, base_name)
        out_file = base_name

        level_keywords.append(Keyword(name, target))

        if not options.force and os.path.exists(out_file) and abs(os.path.getmtime(out_file) - source_mtime) < 1.0:
            options.print("keyword", name, "=", out_file, " # UNCHANGED delta %ss" %
                          str(os.path.getmtime(out_file) - source_mtime))
            continue
        options.print("keyword", name, "=", target)

        # Define path and name for images.
        image_args = [
            "-P", "-D" + "images",
            "-P", "-I" + name + "-",
        ]
        process = subprocess.run("groff -t -m mandoc -mwww -Thtml".split() + image_args,
                                 input=man_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        html_data = process.stdout
        error_text = process.stderr
        if error_text:
            print("entry %s:" % name, error_text, file=sys.stderr)
        if process.returncode != 0:
            print("error running groff: %d. output not written" % process.returncode)
            has_errors = True
            continue

        parser = TitleFinder()
        parser.feed(html_data)

        # Replace all caps title to something more informative.
        html_data = html_data.replace(title_tag(parser.title), title_tag(parser.title.lower() + " | man" + str(level)))

        # Replace all cross-references to other man-pages with links to them, regardless whether they exist or not.
        html_data = MAN_LINK.sub(link_replacer(cross_references), html_data)

        with open(out_file, "w") as o:
            o.write(html_data)

        # Set result file modification time to source time to allow checking changes in future.
        os.utime(out_file, (source_mtime, source_mtime))

    # Restore working directory.
    os.chdir(original_dir)

    level_files = set(os.path.basename(kw.target) for kw in level_keywords if not kw.is_alias)
    for file in os.listdir(out_dir):
        if os.path.isfile(file) and file not in level_files:
            to_remove = os.path.join(out_dir, file)
            options.print("delete", to_remove)
            os.remove(to_remove)

    keywords = set(kw.keyword for kw in level_keywords if not kw.is_alias)
    for file in os.listdir(images_dir):
        match = IMAGE_NAME_RE.match(file)
        if match is not None:
            kw = match.group(1)
            if kw in keywords:
                continue
        to_remove = os.path.join(images_dir, file)
        options.print("delete", to_remove)
        os.remove(to_remove)

    return LevelResult(level_keywords, cross_references, has_errors)


def do_levels(options: Options):
    kws = OrderedDict()
    cross_references = []
    has_errors = False
    for level in options.sources:
        options.print("category", level)
        lkw, cross, errors = do_level(level, options)
        options.print("end category", level)
        kws[level] = lkw
        cross_references.extend(cross)
        has_errors |= errors

    # Qt Help requires that the files included and the project file are in same directory.
    catalog = options.cache_path.join(options.qhp)
    with open(catalog, "w") as o:
        o.write(QHP_TEMPLATE[0].format(namespace=options.qhp_namespace))
        for level, keywords in kws.items():
            o.write(CATEGORY_TEMPLATE[0].format(filter_category="man" + str(level)))
            for kw in keywords:
                o.write('        <keyword name="{}" ref="{}" />\n'.format(kw.keyword, kw.target))
            o.write(CATEGORY_TEMPLATE[1])
            o.write("        <file>html." + level + "/*.html</file>\n")
            o.write("        <file>html." + level + "/images/*</file>\n")
            o.write(CATEGORY_TEMPLATE[2])

        o.write(QHP_TEMPLATE[1])
    print("Wrote catalog to", catalog)
    if has_errors:
        print("Processing had errors and some files were skipped.")
    else:
        print("To actually create the help file, use qhelpgenerator", catalog)


def check_system() -> bool:
    def which(name: str, message: str) -> bool:
        try:
            subprocess.check_output(["which", name], stderr=subprocess.STDOUT)
            return True
        except subprocess.CalledProcessError:
            print("Missing", message)
            return False

    e = which("groff", "main part, groff, the document formatting system")
    e &= which("pnmtopng", "netpbm (or pnmtopng)")
    e &= which("psselect", "psutils (or psselect)")
    return e


def make_argument_parser():
    parser = argparse.ArgumentParser(
        description="man-page to Qt Help converter."
    )
    parser.add_argument("levels", nargs="+", metavar="LEVEL",
                        help="man-page level to add for conversion, such as 2")
    parser.add_argument("--cache-dir", type=str, metavar="DIR", default=".",
                        help="Use given cache root directory instead of current directory.")
    parser.add_argument("-f", "--force", action="store_true", default=False,
                        help="Re-write all files.")
    parser.add_argument("-o", "--output", type=str, default="man.qhp",
                        help="Write to given file instead of man.qhp."
                             " Note, the file will be forced into the cache directory!")
    parser.add_argument("--ignore-system-check", action="store_true", default=False,
                        help="Ignore system check results and process anyways.")
    parser.add_argument("-q", "--quiet", action="store_true", default=False,
                        help="Make less noise.")

    qhp = parser.add_argument_group("Qt Help Project options")
    qhp.add_argument("--namespace", default=DEFAULT_NAMESPACE,
                     help="Namespace to use instead of %s" % DEFAULT_NAMESPACE)

    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)

    return parser


def main(*argv):
    parser = make_argument_parser()
    args = parser.parse_args(args=None if len(argv) == 0 else argv)

    if not (check_system() or args.ignore_system_check):
        sys.exit(1)

    quiet = args.quiet

    def q_print(*p_args, **p_kwargs):
        if not quiet:
            print(*p_args, **p_kwargs)

    options = Options(
        cache_path=BasePath(args.cache_dir),
        qhp=os.path.basename(args.output),
        force=args.force,
        sources=args.levels,
        qhp_namespace=args.namespace,
        quiet=args.quiet,
        print=q_print,
    )
    do_levels(options)


if __name__ == "__main__":
    main()
