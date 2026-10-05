#
# PyPref - Preference game for Windows, *NIX and Pocket PC
# This source code is based on kpref by Azarniy I.V.
# and OpenPref (http://openpref.narod.ru)
#
# Author (version 2.0): Alexander aka amigo <amigo12@newmail.ru> - Aug 2007
# Versions 2.1-2.34: Vadim Zapletin <preference.gixx@mail.ru> - Feb-Mar 2018
# License: GNU GPL
#

J = 11
Q = 12
K = 13
A = 14

class TCard:

        def __init__(self,name=None,mast=None):
                self.CName = name
                self.CMast = mast

        def __repr__(self):
                #return 'TCcard instance: name=%d mast=%d' % (self.CName, self.CMast)
                name = self.CName
                if name > 10:
                        name = ('J','Q','K','A')[name-11]
                else:
                        name = str(name)
                name += ('p','t','b','c')[self.CMast-1]
                return name

        def SetCard(name,mast):
                self.CName = name
                self.CMast = mast

        def __gt__(self,other):
                if isinstance(other,TCard) and self.CMast == other.CMast and self.CName > other.CName:
                        return True
                return False

        def __lt__(self,other):
                if isinstance(other,TCard) and self.CMast == other.CMast and self.CName < other.CName:
                        return True
                return False

        def __eq__(self,other):
                if isinstance(other,TCard) and self.CMast == other.CMast and self.CName == other.CName:
                        return True
                return False

        def __hash__(self):  # py3: __eq__ alone makes the class unhashable
                return self.CName*10 + self.CMast
        def Card2Int(self):
                return self.CName*10 + self.CMast

