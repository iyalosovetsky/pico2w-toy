#
# PyPref - Preference game for Windows, *NIX and Pocket PC
# This source code is based on kpref by Azarniy I.V.
# and OpenPref (http://openpref.narod.ru)
#
# Author (version 2.0): Alexander aka amigo <amigo12@newmail.ru> - Aug 2007
# Versions 2.1-2.34: Vadim Zapletin <preference.gixx@mail.ru> - Feb-Mar 2018
# License: GNU GPL
#

MAX = 9999

class Tncounter:

        def __init__(self,Value=None,Min=None,Max=None):
                if not Max is None:
                        self.nValue = Value
                        self.nMin = Min
                        self.nMax = Max
                elif not Min is None:
                        self.nValue = self.nMin = Value
                        self.nMax = Min
                else:
                        self.nValue = self.nMin = 0
                        self.nMax = MAX

        def __repr__(self):
                return 'Tncounter instance: value=%d min=%d max=%d' % (self.nValue, self.nMin, self.nMax)

        def copy(self,other):
                self.nValue = other.nValue
                self.nMin = other.nMin
                self.nMax = other.nMax

        def next(self):
                self.nValue += 1
                if self.nValue > self.nMax:
                        self.nValue = self.nMin
                return self.nValue

        def prev(self):
                self.nValue -= 1
                if self.nValue < self.nMin:
                        self.nValue = self.nMax
                return self.nValue

def NextGamer(counter):
        counter.next()
        retval = counter.nValue
        counter.prev()
        return retval

def PrevGamer(counter):
        counter.prev()
        retval = counter.nValue
        counter.next()
        return retval

