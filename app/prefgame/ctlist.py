#
# PyPref - Preference game for Windows, *NIX and Pocket PC
# This source code is based on kpref by Azarniy I.V.
# and OpenPref (http://openpref.narod.ru)
#
# Author (version 2.0): Alexander aka amigo <amigo12@newmail.ru> - Aug 2007
# Versions 2.1-2.34: Vadim Zapletin <preference.gixx@mail.ru> - Feb-Mar 2018
# License: GNU GPL
#

class Tclist:

        def __init__(self,limit=0):
                self.limit = limit
                self.items = []

        def __repr__(self):
                s = []
                for x in self.items:
                        #s.append(repr(x))
                        s.append(x)
                return repr(s)

        def __len__(self):
                return len(self.items)

        def At(self,index):
                if index < len(self.items):
                        return self.items[index]
                return None

        def IndexOf(self,item):
                try:
                        return self.items.index(item)
                except:
                        return -1

        def Insert(self,item):
                if not self.limit or len(self.items) < self.limit:
                        self.items.append(item)
                        return len(self.items)-1
                return -1

        def Remove(self,item):
                try:
                        index = self.items.index(item)
                        del self.items[index]
                except:
                        pass

        def RemoveAll(self):
                self.items = []

        def Assign(self,other):
                self.items = [x for x in other.items]
                self.limit = other.limit

        def NextItem(self,index):
                if index >= len(self.items)-1:
                        return None
                return self.items[index+1]

        def PrevItem(self,index):
                if index > 0:
                        return self.items[index-1]
                return None

        def LastItem(self):
                if len(self.items):
                        return self.items[-1]
                return None

        def FirstItem(self):
                if len(self.items):
                        return self.items[0]
                return None

        def Set(self,items):
                self.items = items

        def Count(self):
                return len(self.items)

