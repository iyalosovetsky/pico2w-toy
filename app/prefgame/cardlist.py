#
# PyPref - Preference game for Windows, *NIX and Pocket PC
# This source code is based on kpref by Azarniy I.V.
# and OpenPref (http://openpref.narod.ru)
#
# Author (version 2.0): Alexander aka amigo <amigo12@newmail.ru> - Aug 2007
# Versions 2.1-2.34: Vadim Zapletin <preference.gixx@mail.ru> - Feb-Mar 2018
# License: GNU GPL
#

import sys
from functools import cmp_to_key

from prefgame.card import *
from prefgame.ctlist import *

class TCardList(Tclist):

        sort_func = None

        def __init__(self,limit=0,sort=None):
                Tclist.__init__(self,limit)
                if sort:
                        TCardList.sort_func = sort

        def __repr__(self):
                s = ''
                for x in self.items:
                        s += repr(x) + ' ' 
                return s

        def Exist(self,card,mast=None):
                if mast is None:
                        #name = int(pack/10)
                        #mast = pack%10
                        name = card.CName
                        mast = card.CMast
                else:
                        name = card
                for x in self.items:
                        if x.CName == name and x.CMast == mast:
                                return x
                return None

        def MinCard(self,mast=None):
                y = None
                for x in self.items:
                        if mast is None or mast == x.CMast:
                                if not y or y.CName > x.CName:
                                        y = x
                return y

        def MaxCard(self,mast=None):
                y = None
                for x in self.items:
                        if mast is None or mast == x.CMast:
                                if not y or y.CName < x.CName:
                                        y = x
                return y

        def MinMaxAll(self,mast=None):
                mi,ma,c = None,None,0
                for x in self.items:
                        if mast is None or mast == x.CMast:
                                c += 1
                                if not mi or x.CName < mi.CName:
                                        mi = x
                                if not ma or x.CName > ma.CName:
                                        ma = x
                return (mi,ma,c)

        def AllCard(self,mast=None):
                if not mast:
                        return self.Count()
                counter = 0
                for x in self.items:
                        if mast == x.CMast:
                                counter += 1
                return counter

        def Sort(self):
#               def sort_func(a,b):
#                       #morder = [1,3,2,4]
#                       morder = default.PrefGUI.opt[sorder] and [1,2,3,4] or [1,3,2,4]
#                       return cmp(morder.index(a.Mast),morder.index(b.CMast)) or \
#                               (default.PrefGUI.opt[corder] and cmp(a.CName,b.CName) or cmp(b.CName,a.CName))
                self.items.sort(key=cmp_to_key(TCardList.sort_func))

        def LessThan(self,name,mast=None):
                if isinstance(name,TCard):
                        mast = name.CMast
                        name = name.CName
                elif name is None:
                        return None
                if name == 7:
                        return None
#               for i in range(name-1,6,-1):
#                       x = self.Exist(i,mast)
#                       if x:
#                               return x
#               return None
                y = None
                for x in self.items:
                        if mast == x.CMast and (y and y.CName < x.CName < name or not y and x.CName < name):
                                y = x
                return y

        def MoreThan(self,name,mast=None):
                if isinstance(name,TCard):
                        mast = name.CMast
                        name = name.CName
                elif name is None:
                        return None
                if name == A:
                        return None
#               for i in range(name+1,A+1):
#                       x = self.Exist(i,mast)
#                       if x:
#                               return x
#               return None
                y = None
                for x in self.items:
                        if mast == x.CMast and (y and y.CName > x.CName > name or not y and x.CName > name):
                                y = x
                return y

        def AssignMast(self,oldlist,mast):
                for x in oldlist.items:
                        if x.CMast == mast:
                                self.Insert(x)

        def MiserMast(self,mast):
                tmp = TCardList()
                tmp.Assign(self)
                for name in (8,10,Q,A):
                        if tmp.AllCard(mast):
                                card = tmp.LessThan(TCard(name,mast))
                                if card:
                                        tmp.Remove(card)
                                else:
                                        return False
                        else:
                                break
                return True
