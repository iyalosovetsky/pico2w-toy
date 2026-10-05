#
# PyPref - Preference game for Windows, *NIX and Pocket PC
# This source code is based on kpref by Azarniy I.V.
# and OpenPref (http://openpref.narod.ru)
#
# Author (version 2.0): Alexander aka amigo <amigo12@newmail.ru> - Aug 2007
# Versions 2.1-2.34: Vadim Zapletin <preference.gixx@mail.ru> - Feb-Mar 2018
# License: GNU GPL
#

import random
import time
import sys

from prefgame.card import *
from prefgame.cardlist import *

class TColoda(TCardList):

        def __init__(self,limit=32):
                TCardList.__init__(self,limit)
                self.limit = limit
                for m in range(1,5):
                        for n in range(7,A+1):
                                nc = TCard(n,m)
                                self.Insert(nc)

        def Mix(self):
                random.seed(str(time.time()))
                tmpList = TCardList(32)
                for x in range(0,21):
                        tmpList.Assign(self)
                        self.RemoveAll()
                        while True:
                                n = tmpList.Count()
                                if not n:
                                        break
                                i = random.randint(0,n-1)
                                self.Insert(tmpList.At(i))
                                del tmpList.items[i]

