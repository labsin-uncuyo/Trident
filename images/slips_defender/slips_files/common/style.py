# SPDX-FileCopyrightText: 2021 Sebastian Garcia <sebastian.garcia@agents.fel.cvut.cz>
# SPDX-License-Identifier: GPL-2.0-only
from termcolor import colored


def green(txt):
    return colored(txt, 'green')


def red(txt):
    return colored(txt, 'red')


def cyan(txt):
    return colored(txt, 'cyan')


def yellow(txt):
    return colored(txt, 'yellow')
