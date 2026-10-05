#
# PyPref - Preference game for Windows, *NIX and Pocket PC
# This source code is based on kpref by Azarniy I.V.
# and OpenPref (http://openpref.narod.ru)
#
# Author (version 2.0): Alexander aka amigo <amigo12@newmail.ru> - Aug 2007
# Versions 2.1-2.34: Vadim Zapletin <preference.gixx@mail.ru> - Feb-Mar 2018
# License: GNU GPL
#

import time
import sys

from prefgame.prfconst import *
from prefgame.cardlist import *
from prefgame.plscore import *
from prefgame.ncounter import *

lGamer = None
rGamer = None
Partner = None
Gamer = None

class TGamer:

        dt = None
        gui = None

        def __init__(self,nGamer,app=None,gui=None):
                if app:
                        TGamer.dt = app
                        TGamer.gui = gui
                self.nGamer = nGamer
                self.aScore = TPlScore()
                self.aCards = TCardList(12)
                self.aLeft = TCardList(10)
                self.aRight = TCardList(10)
                self.aOut = TCardList(2)
                self.aCardsOut = TCardList(12)
                self.aLeftOut = TCardList(12)
                self.aRightOut = TCardList(12)
                self.MastTable = [TMastTable() for x in range(0,6)]
                self.RetVal = None
                self.level = 0
                self.set0()

        def set0(self):
                self.flMiser = 0
                self.aCards.RemoveAll()
                self.aLeft.RemoveAll()
                self.aRight.RemoveAll()
                self.aOut.RemoveAll()
                self.aCardsOut.RemoveAll()
                self.aLeftOut.RemoveAll()
                self.aRightOut.RemoveAll()
                self.Mast = withoutmast
                self.GamesType = undefined
                self.MaxGame = undefined
                self.nGetsCard = 0
                self.vzatok = -1
                self.Pronesti = None
                self.opened = False
                self.closed = True
                self.human = False
                self.carry = 0

        def Miser1(self,aLeftGamer,aRightGamer):
                RetVal = None
                if self.GetAll() == 10:
                        for m in (1,2,3,4):
                                if self.GetAll(m) == 1:
                                        RetVal = self.GetMin(m)
                                        break
                                else:
                                        RetVal = self.GetMax(m)
                                        if RetVal:
                                                if RetVal < aLeftGamer.GetMin(m) or RetVal < aRightGamer.GetMin(m):
                                                        break
                                                RetVal = None
                if not RetVal:
                        for m in range(4,0,-1):
                                if RetVal:
                                        break
                                for c in range(A,6,-1):
                                        if RetVal:
                                                break
                                        my = self.aCards.Exist(c,m)
                                        if my:
                                                midx = 0
                                                midx += (aLeftGamer.aCards.LessThan(my) and 1 or 0); midx <<= 1
                                                midx += (aLeftGamer.aCards.MoreThan(my) and 1 or 0); midx <<= 1
                                                midx += (aRightGamer.aCards.LessThan(my) and 1 or 0); midx <<= 1
                                                midx += (aRightGamer.aCards.MoreThan(my) and 1 or 0)
                                                if midx == 1 or midx == 9 or midx == 13 or 4 <= midx <= 7:
                                                        RetVal = my
                if not RetVal:
                        for m in (1,2,3,4):
                                RetVal = self.GetMin(m)
                                if RetVal:
                                        break
                return RetVal

        def Miser2(self,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                if self.GetAll(aRightCard.CMast):
                        for c in range(A,6,-1):
                                if RetVal:
                                        break
                                my = self.aCards.Exist(c,aRightCard.CMast)
                                if my:
                                        midx = 0
                                        midx += (aLeftGamer.aCards.LessThan(my) and 1 or 0); midx <<= 1
                                        midx += (aLeftGamer.aCards.MoreThan(my) and 1 or 0); midx <<= 1
                                        midx += ((aRightCard < my) and 1 or 0); midx <<= 1
                                        midx += ((aRightCard > my) and 1 or 0)
                                        if midx == 1 or midx == 9 or midx == 13 or 4 <= midx <= 7:
                                                RetVal = my
                        if not RetVal:
                                RetVal = self.GetMax(aRightCard.CMast)
                else:
                        RetVal = self.GetMaxCardWithoutPere() or self.GetMaxCardPere() or self.GetMinCardWithoutVz() or self.GetMax()
                return RetVal

        def Miser3(self,aLeftCard,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                if self.GetAll(aLeftCard.CMast):
                        if aLeftCard.CMast == aRightCard.CMast:
                                if aRightCard > aLeftCard:
                                        RetVal = self.aCards.LessThan(aRightCard)
                                else:
                                        RetVal = self.aCards.LessThan(aLeftCard)
                        else:
                                RetVal = self.aCards.LessThan(aLeftCard)
                        if not RetVal:
                                RetVal = self.GetMax(aLeftCard.CMast)
                else:
                        RetVal = self.GetMaxCardWithoutPere() or self.GetMaxCardPere() or self.GetMinCardWithoutVz() or self.GetMax()
                self.GamesType = tmpGamesType
                return RetVal

        def MiserHole(self,mast,lg,rg):
                catch = []
                gamer = []
                for g in (self,lg,rg):
                        for j in range(0,10):
                                card = g.aCards.At(j)
                                if card and card.CMast == mast:
                                        if g.GamesType == g86:
                                                gamer.append(card)
                                        else:
                                                catch.append(card)
                catch.sort(key=lambda a: a.CName)
                gamer.sort(key=lambda a: a.CName)
                cnt = 0
                while len(gamer) and len(catch):
                        cnt += 1
                        card = gamer.pop(0)
                        if card > catch.pop(0):
                                for g in (self,lg,rg):
                                        if g.GamesType == g86catch and cnt <= g.GetAll(mast):
                                                #print 'Hole', card
                                                return card
                return None

        def MiserCatch1(self,aLeftGamer,aRightGamer):
                RetVal = None
                EnemyCardList = Gamer.aCards

                holes,cards = [None],[None]
                for m in (1,2,3,4):
                        holes.append(self.MiserHole(m,aLeftGamer,aRightGamer))
                        cards.append(EnemyCardList.AllCard(m))
                # If we have empty mast and there is "long" holes, we can lead in that empty mast
                for m in (1,2,3,4):
                        if cards[m] == 0:
                                for k in (1,2,3,4):
                                        if holes[k] and EnemyCardList.MoreThan(holes[k]):
                                                cards[m] = -1
                                                break

####################################
                for m in (1,2,3,4):
                        EnemyMin = EnemyCardList.MinCard(m)
                        NaparnikMin = Partner.GetMin(m)
                        MyMin = self.GetMin(m)

                        if EnemyMin:
                                if MyMin:
                                        if NaparnikMin and NaparnikMin > EnemyMin and MyMin < EnemyMin:
                                                for k in (1,2,3,4):
                                                        # I must return lead!
                                                        if k != m and not holes[k] and cards[k]:
                                                                m = self.GetAll(k)
                                                                n = Partner.GetAll(k)
                                                                if m > n:
                                                                        MyMin = self.GetMin(k)
                                                                        if n == 0:
                                                                                Partner.Pronesti = NaparnikMin
                                                                                return MyMin
                                                                        if n == 1:
                                                                                NapMax = Partner.GetMax(k)
                                                                                RetVal = self.aCards.MoreThan(NapMax)
                                                                                if RetVal:
                                                                                        return RetVal

                                        elif MyMin < EnemyMin:
                                                # Try to get ourselfs
                                                # Sort by enemy mast length descending for choo-choo chance
                                                mlist = [1,2,3,4]
                                                if self.level:
                                                        mt = Gamer.MastTable
                                                        mlist.sort(key=lambda a: -mt[a].len)
                                                #for k in (1,2,3,4):
                                                for k in mlist:
                                                        if (not holes[k] or EnemyCardList.MoreThan(holes[k])) and cards[k] > 0: 
                                                                # I must have perehvat
                                                                MyMax = self.GetMax(k)
                                                                if MyMax:
                                                                        NaparnikMin = Partner.GetMin(k)
                                                                        if not NaparnikMin or MyMax > NaparnikMin:
                                                                                return MyMax
                                                                        # Try to look for another suit
                                                                        #for j in (1,2,3,4):
                                                                        for j in mlist:
                                                                                if (not holes[j] or EnemyCardList.MoreThan(holes[j])) and cards[j] > 0:  
                                                                                        MyMax1 = self.GetMax(j)
                                                                                        NaparnikMin = Partner.GetMin(j)
                                                                                        if MyMax1 and NaparnikMin and MyMax1 > NaparnikMin:
                                                                                                return MyMax
                                                return MyMin
                                        elif holes[m] and MyMin > EnemyMin and NaparnikMin < EnemyMin:
                                                if Partner.aCards.MoreThan(holes[m]) and EnemyCardList.MoreThan(holes[m]):
                                                        return MyMin
##############################################
                RetFirst = None
                if not RetVal:
                        #RetVal = self.GetMaxCardWithoutPere() or self.GetMin()
                        #holes = TCardList(4)
                        for m in (1,2,3,4):
                                if self.GetAll(m) and cards[m] > 0:
                                        # I have mast and enemy have mast
                                        hole = holes[m]
                                        if hole:
                                                if Partner == aLeftGamer:
                                                        # Lead to naparnik
                                                        if Partner.GetAll(m) and Partner.aCards.LessThan(hole):
                                                                # Move lead
                                                                for k in (1,2,3,4):
                                                                        if k != m and cards[k]:
                                                                                MyMin = self.GetMin(k)
                                                                                NaparnikMax = Partner.GetMax(k)
                                                                                #if MyMin and NaparnikMax and MyMin < NaparnikMax and not self.MiserHole(k,aLeftGamer,aRightGamer):
                                                                                if MyMin and NaparnikMax and MyMin < NaparnikMax and not holes[k]:
                                                                                        return MyMin
                                                MyLess = self.aCards.LessThan(hole)
                                                if MyLess and (not Partner.GetAll(m) or Partner.aCards.LessThan(hole) and Partner.aCards.MoreThan(hole)):
                                                        return MyLess
                                        else:
                                                # Get ourselfs
                                                n = Partner.GetAll(m)
                                                if self.GetAll(m) > n:
                                                        #RetVal = self.GetMax(m)
                                                        RetVal = self.GetMin(m)
                                                        if n == 0:
                                                                for k in (1,2,3,4):
                                                                        hole = holes[k]
                                                                        if hole:
                                                                                if Partner.aCards.LessThan(hole) and Partner.aCards.MoreThan(hole):
                                                                                        Partner.Pronesti = Partner.aCards.MoreThan(hole)
                                                                        elif cards[k] == 0:
                                                                                # Choo try
                                                                                Partner.Pronesti = Partner.GetMax(k)
                                                                                RetFirst = RetVal
                                                elif Partner.GetAll(m) > 1:
                                                        #RetVal = self.GetMin(m)
                                                        if self.GetAll(m) < Partner.GetAll(m):
                                                                RetVal = self.GetMax(m)
                                                        else:
                                                                RetVal = self.GetMin(m)
####################################
                if not RetVal:
                        # I have no good lead
                        for m in (1,2,3,4):
                                #n = EnemyCardList.AllCard(m)
                                if self.GetAll(m) and cards[m] > 0:
                                        hole = holes[m]
                                        if not hole:
                                                # get chance to partner
                                                return self.GetMin(m)
                                        else:
                                                # hole, but I can lead this suit
                                                card = self.aCards.MoreThan(hole)
                                                #if cards[m] > 1 and card and Partner.aCards.MoreThan(hole):
                                                if card and EnemyCardList.MoreThan(hole) and Partner.aCards.MoreThan(hole):
                                                        RetVal = card
                if not RetVal:
                        RetVal = self.GetMin()
                return RetFirst or RetVal


        def MiserCatch2(self,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                EnemyCardList = Gamer.aCards

                #if aLeftGamer.GamesType == g86:
                if Gamer == aLeftGamer:
                        # enemy left
                        if self.GetAll(aRightCard.CMast):
                                MyMin = self.GetMin(aRightCard.CMast)
                                MyMax = self.GetMax(aRightCard.CMast)
                                EnemyMin = EnemyCardList.MinCard(aRightCard.CMast)
                                if EnemyMin:
                                        if aRightCard < EnemyMin:
                                                RetVal = self.aCards.LessThan(EnemyMin)
                                        if not RetVal:
                                                RetVal = self.aCards.MoreThan(EnemyMin)
                                else:
                                        #RetVal = MyMax # who need lead ???
                                        if self.GetAll(aRightCard.CMast) < Partner.GetAll(aRightCard.CMast):
                                                RetVal = MyMax
                                        else:
                                                RetVal = MyMin
                                        #print "Who need lead", RetVal
                        else:
                                if self.Pronesti:
                                        RetVal = self.GetMax(self.Pronesti.CMast)
                                else:
                                        for m in (1,2,3,4):
                                                RetVal = self.aCards.MoreThan(Gamer.GetMax(m))
                                                if not Gamer.MiserMast(m) and RetVal:
                                                        break
                                if not RetVal:
                                        RetVal = self.GetMaxCardPere() or self.GetMax()
                else:
                        # enemy right
                        MyMin = self.GetMin(aRightCard.CMast)
                        MyMax = self.GetMax(aRightCard.CMast)
                        #print MyMin, MyMax, aRightCard
                        if MyMax:
                                if MyMin < aRightCard:
                                        NapMin = Partner.aCards.LessThan(aRightCard)
                                        #if NapMin: # !!!
                                        #print NapMin, Partner.GetAll(aRightCard.CMast)
                                        if NapMin or not Partner.GetAll(aRightCard.CMast):
                                                RetVal = self.aCards.LessThan(aRightCard)
#                                       else:
#                                               RetVal = MyMax # who need lead ???
#                               else:
#                                       RetVal = MyMax
                                if not RetVal:
                                        #print "Who need lead"
                                        if self.GetAll(aRightCard.CMast) < Partner.GetAll(aRightCard.CMast):
                                                RetVal = MyMax
                                        else:
                                                RetVal = MyMin
                                        #print "Who need lead", RetVal
                        else:
                                RetVal = self.GetMaxCardPere() or self.GetMax()
                self.Pronesti = None
                if not RetVal:
                        RetVal = self.GetMin()
                return RetVal

        def MiserCatch3(self,aLeftCard,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                EnemyCardList = Gamer.aCards
        
                #if aLeftGamer.GamesType == g86:
                if Gamer == aLeftGamer:
                        #print "Catch 3: enemy left"
                        # enemy left
                        if self.GetAll(aLeftCard.CMast):
                                if aLeftCard < aRightCard:
                                        # friend already get it :(
                                        RetVal = self.GetMax(aLeftCard.CMast)
                                else:
                                        # we have a chance
                                        RetVal = self.aCards.LessThan(aLeftCard) or self.GetMax(aLeftCard.CMast)
                        else:
                                if self.Pronesti:
                                        RetVal = self.GetMax(self.Pronesti.CMast) or self.GetMax()
                                else:
                                        RetVal = self.GetMaxCardPere() or self.GetMax()
                else:
                        #print "Catch 3: enemy right"
                        # enemy right

                        MyMin = self.GetMin(aLeftCard.CMast)
                        MyMax = self.GetMax(aLeftCard.CMast)

#                       if MyMax:
#                               if MyMin < aLeftCard:
#                                       NapMin = Partner.aCards.LessThan(aLeftCard)
#                                       if NapMin:
#                                               RetVal = self.aCards.LessThan(aLeftCard)
#                                       else:
#                                               RetVal = MyMax # who need lead ???
#                               else:
#                                       RetVal = MyMax
#                       else:
#                               RetVal = self.GetMaxCardPere() or self.GetMax()
                        if MyMax:
                                #print "aaa"
                                if aLeftCard.CMast == aRightCard.CMast:
                                        #print "bbb"
                                        if aLeftCard > aRightCard:
                                                #print "ccc"
                                                # friend already get it :(
                                                RetVal = MyMax
                                                #print "Catch 3", RetVal
                                        else:
                                                # we have a chance
                                                #RetVal = self.aCards.LessThan(aRightCard) or MyMax
                                                RetVal = self.aCards.LessThan(aRightCard) or self.aCards.MoreThan(aLeftCard)
                                if not RetVal:
                                        #RetVal = MyMax # who need lead ???
                                        if self.GetAll(aLeftCard.CMast) < Partner.GetAll(aLeftCard.CMast):
                                                RetVal = MyMax
                                        else:
                                                RetVal = MyMin
                                        #print "Who need lead", RetVal
                        else:
                                if self.Pronesti:
                                        RetVal = self.GetMax(self.Pronesti.CMast)
                                else:
                                        for m in (1,2,3,4):
                                                # ????!!!! 1. Gamer or Partner; 2. Is is correct?
                                                #RetVal = self.aCards.MoreThan(aLeftGamer.GetMax(m))
                                                #if not aLeftGamer.aCards.MiserMast(m) and RetVal:
                                                #       break
                                                MyMax = self.aCards.MoreThan(Gamer.GetMax(m))
                                                if MyMax and not Gamer.MiserMast(m):
                                                        RetVal = MyMax
                                                        break
                                if not RetVal:
                                        RetVal = self.GetMaxCardPere() or self.GetMax()
                self.Pronesti = None
                return RetVal

        def MyGame3(self,aLeftCard,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                #mast = self.GamesType - (self.GamesType/10) * 10;
                mast = self.GamesType % 10
                if self.GetAll(aLeftCard.CMast):
                        if aLeftCard.CMast == aRightCard.CMast:
                                MaxCard = aLeftCard > aRightCard and aLeftCard or aRightCard
                                RetVal = self.aCards.MoreThan(MaxCard) or self.GetMin(aLeftCard.CMast)
                        else:
                                if aRightCard.CMast != mast:
                                        RetVal = self.aCards.MoreThan(aLeftCard) or self.GetMin(aLeftCard.CMast)
                                else:
                                        RetVal = self.GetMin(aLeftCard.CMast)
                else:
                        if aLeftCard.CMast == aRightCard.CMast:
#                               if aLeftCard > aRightCard:
#                                       MaxCard = aLeftCard
#                               else:
#                                       MaxCard = aRightCard # ???
                                MaxCard = aLeftCard > aRightCard and aLeftCard or aRightCard
                        else:
                                if aLeftCard.CMast != mast and aRightCard.CMast != mast:
                                        MaxCard = aLeftCard
                                else:
                                        MaxCard = aRightCard
                        RetVal = self.aCards.MoreThan(MaxCard) or self.GetMin(mast) or self.GetMinCardWithoutVz() or self.GetMin()
                self.GamesType = tmpGamesType
                return RetVal

        def MyGame2(self,aRightCard,aLeftGamer,aRightGamer):
                tmpGamesType = self.GamesType
                mast = aRightCard.CMast;
                #koz = self.GamesType - (self.GamesType/10) * 10;
                koz = self.GamesType % 10
                RetVal = self.GetMax(mast)
                if not RetVal:
                        if not aLeftGamer.GetAll(mast):
                                MaxLeftCard = aLeftGamer.GetMax(koz)
                                RetVal = self.aCards.MoreThan(MaxLeftCard) or self.aCards.LessThan(MaxLeftCard) or self.GetMin(koz) \
                                                        or self.GetMinCardWithoutVz() or self.GetMin()
                        else:
                                RetVal = self.GetMin(koz) or self.GetMin()
                else:
                        if aLeftGamer.GetAll(mast):
                                MaxLeftCard = aLeftGamer.GetMax(mast)
                                RetVal = self.aCards.MoreThan(MaxLeftCard) or self.aCards.LessThan(MaxLeftCard)
                        else:
                                if not aLeftGamer.GetAll(koz):
                                        RetVal = self.aCards.MoreThan(aRightCard) or self.GetMin(mast)
                                else:
                                        RetVal = self.GetMin(mast)
                self.GamesType = tmpGamesType
                return RetVal

        def MyGame1(self,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                #mast = self.GamesType - (self.GamesType/10) * 10;
                mast = self.GamesType % 10
                #if self.aLeft.AllCard(mast) or self.aRight.AllCard(mast):
                if aLeftGamer.GetAll(mast) or aRightGamer.GetAll(mast):
                        #RetVal = self.Dostacha() or self.GetTrumps() or self.PlayLongMast() \
                        #       or self.GetMax(mast) or self.GetMaxCardWithoutPere() \
                        #       or self.GetMaxCardPere()        or self.GetMinCardWithoutVz() or self.GetMax()
                        RetVal = self.Dostacha() or self.PlayLongMast() or self.GetTrumps() \
                                or self.GetMaxCardPere() or self.GetMaxCardWithoutPere() \
                                or self.GetMinCardWithoutVz() or self.GetMax()
                else:
                        #RetVal = self.GetBigBlank() or self.PlayLongMast() \
                        RetVal = self.PlayLongMast() \
                                or self.GetMaxCardPere() or self.GetMaxCardWithoutPere() or self.GetMinCardWithoutVz() \
                                or self.GetMax(mast) or self.GetMax()
                self.GamesType = tmpGamesType
                return RetVal

        def GetTrumps(self):
                dt = TGamer.dt
                if not self.level:
                        return self.GetMax(dt.Trump)
                mt = self.MastTable[dt.Trump]
                #if mt.elen and mt.perehvatov >= mt.elen:
                #if mt.elen and mt.perehvatov >= mt.elen and mt.len-mt.elen > 2:
                #if mt.elen and mt.perehvatov >= mt.elen: <- comment for rx40
                if mt.elen:
                        return mt.max
                #return None
                return self.GetBigBlank(dt.Trump)

        def PlayLongMast(self):
                if not self.level:
                        return None
                dt = TGamer.dt
                trump = dt.Trump
                mtr = self.MastTable[trump]
                # force GetTrumps() if player have many trumps
                if mtr.elen and mtr.len == mtr.vzatok and mtr.len-mtr.elen >= 2:
                        return None
                for m in (1,2,3,4):
                        if m != trump:
                                mt = self.MastTable[m]
                                #if mt.vzatok and mt.elen and mt.len > mt.vzatok and mt.len > mt.elen:
                                #if mt.vzatok and mt.perehvatov < mt.elen < mt.len:
                                if mt.vzatok and mt.len > mt.vzatok:
                                        # if don't have enouth trumps
                                        #if not mtr.elen or mtr.len <= mtr.elen:
                                        if True:
                                                #card = mt.elen > 1 and mt.perehvatov < mt.elen and mt.min or mt.max
                                                #? card = mt.vzatok < mt.len and mt.min or mt.max
                                                card = mt.max
                                                return card
                                if mtr.elen > mtr.len and mt.len and not mt.elen:
                                        return mt.min
                                if not mtr.elen and mt.len and not mt.elen:
                                        return mt.min
                                # rx42 rx44
                                if mtr.elen and not mtr.vzatok and mt.len:
                                        return mt.max
                return None

        def GetBigBlank(self,mast=None):
                list = mast and (mast,) or (1,2,3,4)
                for m in list:
                        mt = self.MastTable[m]
                        if mt.len > 1:
                                lmt = lGamer.MastTable[m]
                                rmt = rGamer.MastTable[m]
                                if lmt.len == 1 and lmt.perehvatov or rmt.len == 1 and rmt.perehvatov:
                                        return mt.min
                return None

        def Dostacha(self):
                if not self.level:
                        return None
                dt = TGamer.dt
                trump = dt.Trump
                for m in (1,2,3,4):
                        if m != trump:
                                mt = self.MastTable[m]
                                #if mt.vzatok > 1 and mt.vzatok < mt.len:
                                if mt.vzatok and mt.vzatok < mt.len:
                                        next,last = lGamer.MastTable,rGamer.MastTable
                                        if next[trump].len and not next[m].len or last[trump].len and not last[m].len:
                                                return mt.min
                return None

        def MyVist3(self,aLeftCard,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                mast = Gamer.GamesType % 10
                if self.GetAll(aLeftCard.CMast):
                        if Gamer == aLeftGamer:
                                if aLeftCard.CMast == aRightCard.CMast:
                                        if aRightCard > aLeftCard:
                                                #RetVal = self.GetMin(aRightCard.CMast)
                                                RetVal = self.CanRemiz(aRightCard.CMast) and self.aCards.MoreThan(aRightCard) or self.GetMin(aRightCard.CMast)
                                        else:
                                                RetVal = self.aCards.MoreThan(aLeftCard) or self.GetMin(aLeftCard.CMast)
                                else:
                                        if aRightCard.CMast != mast:
                                                RetVal = self.aCards.MoreThan(aLeftCard) or self.GetMin(aLeftCard.CMast)
                                        else:
                                                RetVal = self.GetMin(aLeftCard.CMast)
                        else:
                                if aLeftCard.CMast == aRightCard.CMast:
                                        if aRightCard > aLeftCard:
                                                RetVal = self.aCards.MoreThan(aRightCard) or self.GetMin(aRightCard.CMast)
                                        else:
                                                #RetVal = self.GetMin(aRightCard.CMast)
                                                RetVal = self.CanRemiz(aRightCard.CMast) and self.aCards.MoreThan(aLeftCard) or self.GetMin(aRightCard.CMast)
                                else:
                                        if aRightCard.CMast == mast:
                                                RetVal = self.GetMin(aLeftCard.CMast)
                                        else:
                                                RetVal = self.GetMin(aLeftCard.CMast)
                else:
##############################################################
#                       if aLeftCard.CMast == aRightCard.CMast:
#                               if aLeftCard > aRightCard:
#                                       MaxCard = aLeftCard
#                               else:
#                                       MaxCard = aRightCard # ???
#                       elif aLeftCard.CMast != mast and aRightCard.CMast != mast:
#                               MaxCard = aLeftCard
#                       elif aRightCard.CMast == mast and aEnemy == aRightGamer:
#                               MaxCard = aRightCard
#                       else:
#                               MaxCard = None
#                       if MaxCard:
#                               if aEnemy == aLeftGamer:
#                                       self.LoadLists(aRightGamer,aRightGamer,aMaxCardList)
#                                       self.RecountTables(aMaxCardList,23)
#                                       if MaxCard == aLeftCard:
#                                               RetVal = self.GetMin(MaxCard.CMast)
#                                       else:
#                                               RetVal = self.aCards.MoreThan(aLeftCard)
#                       if not RetVal:
#                               RetVal = self.GetMin(mast) or self.GetMinCardWithoutVz() or self.GetMin()
##############################################################
                        # I dont't have such mast
                        RetVal = self.GetMin(mast) or self.GetMinCardWithoutVz() or self.GetMin()
                self.GamesType = tmpGamesType
                return RetVal

        def MyVist2(self,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                mast = Gamer.GamesType % 10
                if Gamer == aLeftGamer:
                        if self.level < 2:
                                if aRightCard.CName >= 10:
                                        RetVal = self.GetMin(aRightCard.CMast)
                                else:
                                        RetVal = self.GetMax(aRightCard.CMast)
                                if not RetVal:
                                        RetVal = self.GetMax(mast) or self.GetMinCardWithoutVz()
                        else:
                                # LEVEL OPEN
                                RetVal = self.CanGet(aRightCard) or self.GetMin(aRightCard.CMast)
                                if not RetVal:
                                        RetVal = self.GetMin(mast) or self.GetMinCardWithoutVz()
                else:
                        RetVal = self.aCards.MoreThan(aRightCard)
                        # LEVEL OPEN
                        #if RetVal and Partner.aCards.MoreThan(aRightCard):
                        #if self.level >= 2 and RetVal:
                        if RetVal and (Partner.opened or self.level >= 2):
                                fmore = Partner.aCards.MoreThan(aRightCard)
                                if fmore and fmore < RetVal:
                                        RetVal = None
                        if not RetVal:
                                RetVal = self.GetMin(aRightCard.CMast) or self.GetMin(mast) or self.GetMinCardWithoutVz()
                if not RetVal:
                        RetVal = self.GetMin()
                self.GamesType = tmpGamesType
                self.Pronesti
                return RetVal

        def MyVist1(self,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                mast = Gamer.GamesType % 10
                if Gamer == aLeftGamer:
                        if Gamer.GetAll(mast) <= 2:
                                myMax = self.GetMax(mast)
#                               if not myMax:
#                                       RetVal = self.GetMin(aLeftGamer.aCards.EmptyMast(mast))
#                               else:
#                                       #if aLeftGamer.GetMax(mast).CName < m.CName:
#                                       #       RetVal = self.GetMax(mast)
#                                       leftMax = aLeftGamer.GetMax(mast)
#                                       if not leftMax or leftMax < myMax:
#                                               RetVal = myMax
#                                       else:
#                                               RetVal = self.GetMin(aLeftGamer.aCards.EmptyMast(mast))
#                       else:
#                               RetVal = self.GetMin(aLeftGamer.aCards.EmptyMast(mast))
                                if myMax and self.level >= 2:
                                        leftMax = Gamer.GetMax(mast)
                                        if not leftMax or leftMax < myMax:
                                                RetVal = myMax
                        if not RetVal:
                                #RetVal = self.Ship() or self.Surcup() or self.Cutting() or self.GetLeadInBlank(Gamer)
                                RetVal = self.CanRemiz() or self.GetLeadInBlank() or self.Othod()
                        if not RetVal:
                                RetVal = self.GetMinCardWithoutVz() or self.GetMaxCardWithoutPere() or self.GetMin(mast) or self.GetMaxCardPere() or self.GetMin()
                else:
                        if self.level:
                                RetVal = self.Ship() or self.Surcup() or self.GetLeadInBlank() or self.HandOver() or self.Othod()
                        if not RetVal:
                                RetVal = self.GetMaxCardWithoutPere() or self.GetMaxCardPere() or self.GetMax()
                self.GamesType = tmpGamesType
                return RetVal

        def Surcup(self):
                if Partner.opened or self.level >= 2:
                        dt = TGamer.dt
                        trump = dt.Trump
                        nap,ene = Partner,Gamer
                        for m in (1,2,3,4):
                                if m != trump:
                                        min_card = self.GetMin(m)
                                        if min_card and nap.GetAll(m) == 0 and ene.GetAll(m) == 0:
                                                if self.GetAll(trump) > 1 and nap.GetAll(trump) == 1 and ene.GetAll(trump) and self.GetMax(trump) > ene.GetMin(trump):
                                                        #if ene.GetMax(trump) > nap.GetMax(trump) > ene.GetMin(trump):
                                                        if nap.GetMax(trump) > ene.GetMin(trump):
                                                                return min_card
                return None

        def Cutting(self):
                if Partner.opened or self.level >= 2:
                        dt = TGamer.dt
                        trump = dt.Trump
                        next,last = lGamer,rGamer
                        for m in (1,2,3,4):
                                (self_min,self_max,n) = self.GetMinMaxAll(m)
                                #if self_min and not (n == 2 and self_max.CName == K or n == 3 and self_max.CName == Q):
                                if self_min and not self.vzatok4vist(m):
                                        #next_min = next.GetAll(m) > 1 and next.GetMin(m)
                                        next_min = next.GetMin(m)
                                        last_max = last.GetMax(m)
                                        #if next_min and self_min < next_min and last.GetAll(m) >= next.GetAll(m):
                                        if next_min and last_max and self_min < next_min:
                                                next_max = next.GetMax(m)
                                                while next_max:
                                                        if last_max < next_max:
                                                                break
                                                        next_max = next.aCards.LessThan(next_max)
                                                        last_max = next.aCards.LessThan(last_max)
                                                if not next_max:
                                                        return self_min
                return None

        def CanRemiz(self,mast=None):
                if not self.level:
                        if mast:
                                return self.GetMin(mast)
                        else:
                                return None
                return self.Ship() or self.Surcup() or self.Cutting()

        def Ship(self):
                if Partner.opened or self.level >= 2:
                        dt = TGamer.dt
                        trump = dt.Trump
                        nap,ene = Partner,Gamer
                        for m in (1,2,3,4):
                                if m != trump:
                                        ene_min = ene.GetMin(m)
                                        self_max = self.GetMax(m)
                                        if ene_min and self_max and self_max < ene_min:
                                                if nap.GetAll(m) == 0:
                                                        nap_trumps = nap.GetAll(trump)
                                                        if nap_trumps > nap.vzatok4vist(trump):
                                                                return self.GetMin(m)
                return None

        def HandOver(self):
                if Partner.opened or self.level >= 2:
                        dt = TGamer.dt
                        trump = dt.Trump
                        nap,ene = Partner,Gamer
                        for m in (1,2,3,4):
                                self_min = self.GetMin(m)
                                if self_min and nap.CanGet(self_min):
                                        return self_min
                return None

        def CanGet(self,right_card):
                if Partner.opened or self.level >= 2:
                        dt = TGamer.dt
                        ene = Gamer 
                        mast = right_card.CMast
                        ene_max = ene.GetMax(mast)
                        if not ene_max:
                                if self.GetAll(mast):
                                        return None
                                trump = dt.Trump
                                ene_max = ene.GetMax(trump)
                                if not ene_max:
                                        return None
                        #elif n == 2 and ene_max.CName != K or n == 3 and ene_max.CName != Q:
                        elif ene.vzatok4vist(mast) and ene.vzatok4vist(mast) != ene.vzatok4game(mast):
                                return None
                        self_max = self.aCards.MoreThan(ene_max)
                        if self_max:
                                return self_max
                return None

        def Othod(self,raspas=False):
                if not self.level:
                        return None
                if Partner and Partner.opened or self.level >= 2:
                        dt = TGamer.dt
                        trump = dt.Trump
                        nap,ene = Partner,Gamer
                        for m in (1,2,3,4):
                                if m != trump:
                                        mt = self.MastTable[m]
                                        ### first 'if' can made "naigrysh", second one better
                                        #if mt.othodov:
                                        #if mt.othodov and not mt.perehvatov: <- comment for rsp5
                                        if mt.othodov and (raspas or not mt.perehvatov):
                                                #card = mt.max ?????
                                                card = mt.min
                                                return card
                return None

        def GetLeadInBlank(self):
                dt = TGamer.dt
                trump = dt.Trump
                nap,ene,next = Partner,Gamer,lGamer
                for m in (1,2,3,4):
                        self_min = self.GetMin(m)
                        if self_min:
                                n = ene.GetAll(m)
                                if not self.level:
                                        if n == 0:
                                                return self_min
                                        continue
                                if nap.GetAll(m):
                                        if n == 0:
                                                return (ene == next and self_min or self.GetMax(m))
                                        # Try to get last card in mast
                                        if n == 1:
                                                ene_max = ene.GetMax(m)
                                                nap_more = nap.aCards.MoreThan(ene_max)
                                                if nap_more and nap.CanRemiz():
                                                        return self_min
                                                self_more = self.aCards.MoreThan(ene_max)
                                                if self_more:
                                                        return self_more
                                                if nap_more:
                                                        return self_min
                                elif n == 0 and not ene.GetAll(trump) and not nap.GetAll(trump):
                                        return self_min
                return None

        def GetMaxCardPere(self):
                index = vz = pere = 0
                for i in (1,2,3,4):
                        if self.MastTable[i].vzatok > vz or self.MastTable[i].vzatok == vz and self.MastTable[i].perehvatov > pere:
                        #if self.MastTable[i].vzatok > vz or self.MastTable[i].vzatok == vz:
                                index = i
                                vz = self.MastTable[i].vzatok
                                pere = self.MastTable[i].perehvatov
                #if index:
                if index and self.MastTable[index].perehvatov:
                        return self.GetMax(index)
                return None

        def GetMaxCardWithoutPere(self):
                index = vz = 0
                pere = 10
                for i in (1,2,3,4):
                        if self.MastTable[i].vzatok > vz or self.MastTable[i].vzatok == vz and self.MastTable[i].perehvatov < pere:
                        #if self.MastTable[i].vzatok > vz or self.MastTable[i].vzatok == vz:
                                index = i
                                vz = self.MastTable[i].vzatok
                                pere = self.MastTable[i].perehvatov
                #if index:
                if index and not self.MastTable[index].perehvatov:
                        return self.GetMax(index)
                return None

        def GetMinCardWithoutVz(self):
                if self.GamesType == vist or self.GamesType == pas:
                        ene,nap = Gamer,Partner
                        if ene:
                                ret = None
                                #if self.closed and nap.human and self.carry < 2:
                                if False and self.closed and self.carry < 2:
                                        self.carry += 1
                                        idx = 0
                                        if self.carry == 1:
                                                # strong mast out
                                                max_len,max_sum = 0,0
                                                for i in (1,2,3,4):
                                                        mt = self.MastTable[i]
                                                        if mt.len > max_len or mt.len == max_len and mt.sum > max_sum:
                                                                max_len,max_sum,idx = mt.len,mt.sum,i
                                        elif self.carry == 2:
                                                # weak mast out
                                                #max_len,max_sum,idx = 10,0,0
                                                max_len,idx = 10,0
                                                for i in (1,2,3,4):
                                                        mt = self.MastTable[i]
                                                        #if mt.len and mt.len < max_len or mt.len == max_len and mt.sum < max_sum:
                                                        if mt.len and not mt.vz23 and mt.len < max_len:
                                                                #max_len,max_sum,idx = mt.len,mt.sum,i
                                                                max_len,idx = mt.len,i
                                        if idx:
                                                ret = self.MastTable[idx].min
                                if not ret:
                                        for i in (1,2,3,4):
                                                emt = ene.MastTable[i]
                                                mt = self.MastTable[i]
                                                if mt.len:
                                                        # LEVEL for low use mt.min (not mt.max)
                                                        if not emt.len:
                                                                #ret = mt.max
                                                                ret = mt.min
                                                        elif not mt.vz23:
                                                                #ret = mt.max
                                                                ret = mt.min
                                                        #if not ret and mt.min23 > mt.vz23: <- bad
                                                        if not ret and mt.len > emt.len:
                                                                ret = mt.min
                                if ret:
                                        return ret

                index = 0
                koef = koef1 = 0.0
                for i in (1,2,3,4):
                        koef1 = float(self.MastTable[i].len) + 8. / float(1 + self.MastTable[i].vzatok)
                        if koef1 > koef and self.MastTable[i].len != 0 or self.MastTable[i].vzatok == 0 and self.MastTable[i].len > 0:
                                index = i
                                koef = koef1
                        #print "GetMinCardWithoutVz", koef,koef1,index
                if index:
                        return self.GetMin(index)
                return None

        def MakeMastTable(self,aLeftGamer,aRightGamer,mode=None):
                self.MastTable[0].reset()
                max_list = TCardList(20)
                self_list = TCardList(12)
                self_list.Assign(self.aCards)
                self.aLeft.Assign(aLeftGamer.aCards)
                self.aRight.Assign(aRightGamer.aCards)
                tricks4min = self.GamesType == raspas or self.GamesType == g86 or self.GamesType == g86catch
                #count23 = mode and not tricks4min
                count23 = not tricks4min
                #gamer = None
                gamer = aLeftGamer.GamesType > pas and aLeftGamer or aRightGamer.GamesType > pas and aRightGamer
                if count23:
                        self23_list = TCardList(10)
                        self23_list.Assign(self_list)
                        max23_list = TCardList(10)
                        #if self.GamesType == pas or self.GamesType == vist:
                        if gamer and self.GamesType == pas or self.GamesType == vist:
                                #gamer = aLeftGamer.GamesType > pas and aLeftGamer or aRightGamer
                                #max_list.Assign(gamer.aCards)
                                max23_list.Assign(gamer.aCards)
                last_out = self.aCardsOut.LastItem()
                if last_out:
                        mast_list = (last_out.CMast,)
                else:
                        mast_list = (1,2,3,4)

                for m in mast_list:
                        self.MastTable[m].reset()
                        if gamer:
                                max_list.Assign(gamer.aCards)
                                eMin,eMax,n = gamer.aCards.MinMaxAll(m)
                                self.MastTable[m].elen = n
                        else:
                                l_len = self.aLeft.AllCard(m)
                                r_len = self.aRight.AllCard(m)
                                big,small,n = l_len > r_len and (self.aLeft,self.aRight,l_len) or (self.aRight,self.aLeft,r_len)
                                eMax = eMin = None
                                self.MastTable[m].elen = n
                                while n > 0:
                                        big_min = tricks4min and big.MaxCard(m) or big.MinCard(m)
                                        small_max = small.MaxCard(m)
                                        if small_max and small_max > big_min:
                                                Max = small_max
                                        else:
                                                Max = big_min
                                        if small_max:
                                                small.Remove(small_max)
                                        big.Remove(big_min)
                                        max_list.Insert(Max)
                                        if not eMax or eMax < Max:
                                                eMax = Max
                                        if not eMin or eMin > Max:
                                                eMin = Max
                                        n -= 1

                        if count23:
                                if self.GamesType > pas and self.GamesType != g86:
                                        max23_list.Assign(max_list)
                                n = 0
                                while True:
                                        Ene = max23_list.MaxCard(m)
                                        if not Ene:
                                                break
                                        Max = self23_list.MoreThan(Ene) or self23_list.MinCard(m)
                                        if not Max:
                                                break
                                        n += 1
                                        if Max > Ene:
                                                self.MastTable[m].vz23 += 1
                                                self.MastTable[m].min23 = n
                                        max23_list.Remove(Ene)
                                        self23_list.Remove(Max)

                        while True:
                                Card = tricks4min and self_list.MinCard(m) or self_list.MaxCard(m)
                                if not Card:
                                        break
                                self.MastTable[m].len += 1
                                self.MastTable[m].sum += Card.CName
                                if not self.MastTable[m].max or self.MastTable[m].max < Card:
                                        self.MastTable[m].max = Card
                                if not self.MastTable[m].min or self.MastTable[m].min > Card:
                                        self.MastTable[m].min = Card
                                if Card > eMax:
                                        self.MastTable[m].perehvatov += 1
                                if Card < eMin:
                                        self.MastTable[m].othodov += 1
                                if tricks4min:
                                        Ene = max_list.LessThan(Card) or max_list.MaxCard(m)
                                else:
                                        Ene = max_list.MoreThan(Card) or max_list.MinCard(m)
                                if Ene:
                                        if Card > Ene:
                                                self.MastTable[m].vzatok += 1
                                        max_list.Remove(Ene)
                                #else:
                                elif not tricks4min:
                                        self.MastTable[m].vzatok += 1
                                self_list.Remove(Card)

                mt0 = self.MastTable[0]
                for m in (1,2,3,4):
                        mt0.vzatok += self.MastTable[m].vzatok
                        mt0.vz23 += self.MastTable[m].vz23
                        mt0.len += self.MastTable[m].len
                        card = self.MastTable[m].max
                        if card and (not mt0.max or card.CName > mt0.max.CName):
                                mt0.max = card
                        card = self.MastTable[m].min
                        if card and (not mt0.min or card.CName < mt0.min.CName):
                                mt0.min = card
                if last_out:
                        left_out = aLeftGamer.aCardsOut.LastItem()
                        m = left_out.CMast
                        if last_out.CMast != m:
                                self.MastTable[m].elen = max(self.aLeft.AllCard(m),self.aRight.AllCard(m))
                        right_out = aRightGamer.aCardsOut.LastItem()
                        m = right_out.CMast
                        if last_out.CMast != m and left_out.CMast != m:
                                self.MastTable[m].elen = max(self.aLeft.AllCard(m),self.aRight.AllCard(m))
                #print self

        def MakeMastTableOld(self,aLeftGamer,aRightGamer,mode=None):
                self.MastTable[0].reset()
                max_list = TCardList(20)
                self_list = TCardList(12)
                self_list.Assign(self.aCards)
                self.aLeft.Assign(aLeftGamer.aCards)
                self.aRight.Assign(aRightGamer.aCards)
                tricks4min = self.GamesType == raspas or self.GamesType == g86 or self.GamesType == g86catch
                #count23 = mode and not tricks4min
                count23 = not tricks4min
                gamer = None
                if count23:
                        self23_list = TCardList(10)
                        self23_list.Assign(self_list)
                        max23_list = TCardList(10)
                        if self.GamesType == pas or self.GamesType == vist:
                                gamer = aLeftGamer.GamesType > pas and aLeftGamer or aRightGamer
                                max_list.Assign(gamer.aCards)
                                max23_list.Assign(gamer.aCards)
                last_out = self.aCardsOut.LastItem()
                if last_out:
                        mast_list = (last_out.CMast,)
                else:
                        mast_list = (1,2,3,4)

                for m in mast_list:
                        self.MastTable[m].reset()
                        if gamer:
                                eMin,eMax,n = gamer.aCards.MinMaxAll(m)
                                self.MastTable[m].elen = n
                        else:
                                l_len = self.aLeft.AllCard(m)
                                r_len = self.aRight.AllCard(m)
                                big,small,n = l_len > r_len and (self.aLeft,self.aRight,l_len) or (self.aRight,self.aLeft,r_len)
                                eMax = eMin = None
                                self.MastTable[m].elen = n
                                while n > 0:
                                        big_min = tricks4min and big.MaxCard(m) or big.MinCard(m)
                                        small_max = small.MaxCard(m)
                                        if small_max and small_max > big_min:
                                                Max = small_max
                                        else:
                                                Max = big_min
                                        if small_max:
                                                small.Remove(small_max)
                                        big.Remove(big_min)
                                        max_list.Insert(Max)
                                        if not eMax or eMax < Max:
                                                eMax = Max
                                        if not eMin or eMin > Max:
                                                eMin = Max
                                        n -= 1

                        if count23:
                                if self.GamesType > pas and self.GamesType != g86:
                                        max23_list.Assign(max_list)
                                n = 0
                                while True:
                                        Ene = max23_list.MaxCard(m)
                                        if not Ene:
                                                break
                                        Max = self23_list.MoreThan(Ene) or self23_list.MinCard(m)
                                        if not Max:
                                                break
                                        n += 1
                                        if Max > Ene:
                                                self.MastTable[m].vz23 += 1
                                                self.MastTable[m].min23 = n
                                        max23_list.Remove(Ene)
                                        self23_list.Remove(Max)

                        while True:
                                Max = self_list.MaxCard(m)
                                if not Max:
                                        break
                                self.MastTable[m].len += 1
                                self.MastTable[m].sum += Max.CName
                                if not self.MastTable[m].max or self.MastTable[m].max < Max:
                                        self.MastTable[m].max = Max
                                if not self.MastTable[m].min or self.MastTable[m].min > Max:
                                        self.MastTable[m].min = Max
                                Ene = max_list.MoreThan(Max) or max_list.MinCard(m)
                                if Ene:
                                        if Max > eMax:
                                                self.MastTable[m].perehvatov += 1
                                        if Max < eMin:
                                                self.MastTable[m].othodov += 1
                                        if Max > Ene:
                                                self.MastTable[m].vzatok += 1
                                        max_list.Remove(Ene)
                                else:
                                        self.MastTable[m].vzatok += 1
                                self_list.Remove(Max)

                mt0 = self.MastTable[0]
                for m in (1,2,3,4):
                        mt0.vzatok += self.MastTable[m].vzatok
                        mt0.vz23 += self.MastTable[m].vz23
                        mt0.len += self.MastTable[m].len
                        card = self.MastTable[m].max
                        if card and (not mt0.max or card.CName > mt0.max.CName):
                                mt0.max = card
                        card = self.MastTable[m].min
                        if card and (not mt0.min or card.CName < mt0.min.CName):
                                mt0.min = card
                if last_out:
                        left_out = aLeftGamer.aCardsOut.LastItem()
                        m = left_out.CMast
                        if last_out.CMast != m:
                                self.MastTable[m].elen = max(self.aLeft.AllCard(m),self.aRight.AllCard(m))
                        right_out = aRightGamer.aCardsOut.LastItem()
                        m = right_out.CMast
                        if last_out.CMast != m and left_out.CMast != m:
                                self.MastTable[m].elen = max(self.aLeft.AllCard(m),self.aRight.AllCard(m))

        #def makemove4out(self,MastTable=None):
        def makemove4out(self,getmaxmast=None):
                nMaxMastLen = 0
                nMaxMast = withoutmast
#               LocalMastTable = MastTable or [TMastTable() for x in range(0,5)]
#               for i in (1,2,3,4):
#                       LocalMastTable[i] = self.vzatok4game_(i,1)
#                       LocalMastTable[0].vzatok += LocalMastTable[i].vzatok
#                       LocalMastTable[0].perehvatov += LocalMastTable[i].perehvatov
#                       LocalMastTable[0].sum += LocalMastTable[i].sum
                LocalMastTable = self.MastTable
                # may be kozyr
                for i in (1,2,3,4):
                        if self.GetAll(i) > nMaxMastLen:
                                nMaxMastLen = self.GetAll(i)
                                nMaxMast = i
                # long masts
                for i in (1,2,3,4):
                        if self.aCards.AllCard(i) == nMaxMastLen and nMaxMast != i:
                                if LocalMastTable[i].sum > LocalMastTable[nMaxMast].sum:
                                        nMaxMast = i
                #if MastTable:
                if getmaxmast:
                        return nMaxMast
                GamesTypeRetVal = LocalMastTable[0].vzatok*10 + nMaxMast
                return GamesTypeRetVal

        def makeout4miser(self):
                dt = TGamer.dt
                counter = Tncounter(self.nGamer,1,3)
                left = dt.Gamer(counter.next())
                right = dt.Gamer(counter.next())
                self.MakeMastTable(left,right)

                mt = self.MastTable
                mlist = [1,2,3,4]
                mlist.sort(key=lambda a: mt[a].len)
                for m in mlist:
                        while not self.MiserMast(m,True) and self.aOut.Count() < 2:
                                card = self.GetMax(m)
                                self.aCards.Remove(card)
                                self.aOut.Insert(card)
                                self.MakeMastTable(left,right)

                while self.aOut.Count() < 2:
                        card = self.GetMax()
                        self.aCards.Remove(card)
                        self.aOut.Insert(card)
                        self.MakeMastTable(left,right)

                self.aCards.Sort()
                return g86

        def makeout4game(self):
                dt = TGamer.dt
                counter = Tncounter(self.nGamer,1,3)
                left = dt.Gamer(counter.next())
                right = dt.Gamer(counter.next())
                self.MakeMastTable(left,right)

                # Make Out
                list = [1,2,3,4]
                while self.aOut.Count() < 2:
                        vz,ln,idx = 10,0,0
                        for i in len(list) and list or (1,2,3,4):
                                mt = self.MastTable[i]
                                if mt.len and mt.min.CName != A and (not len(list) or mt.len > mt.perehvatov) and (mt.vzatok < vz or mt.vzatok == vz and mt.len < ln):
                                        vz,ln,idx = mt.vzatok,mt.len,i
                        card = self.MastTable[idx].min
                        self.aCards.Remove(card)
                        self.aOut.Insert(card)
                        self.MakeMastTable(left,right)
                        if len(list) and self.MastTable[idx].vzatok < vz:
                                if idx:
                                        list.remove(idx)
                                else:
                                        list = []
                                self.aOut.Remove(card)
                                self.aCards.Insert(card)
                                self.MakeMastTable(left,right)

                # Set trump
                trump1 = trump2 = None
                ln,sum,elen,vz = 0,0,10,0
                for i in (4,3,2,1):
                        mt = self.MastTable[i]
                        if mt.len:
                                if mt.len > ln:
                                        trump1,trump2,ln,sum,elen,vz = i,i,mt.len,mt.sum,mt.elen,mt.vzatok
                                #elif mt.len == ln and (dt.nCurrentStart.nValue == self.nGamer and mt.sum > sum or mt.sum < sum):
                                #elif mt.len == ln and mt.vzatok >= vz:
                                elif mt.len == ln:
                                        if self.level == 0 and mt.sum > sum \
                                        or self.level == 1 and (dt.nCurrentStart.nValue == self.nGamer and mt.sum > sum or mt.sum < sum) \
                                        or self.level == 2 and (mt.elen < elen or (dt.nCurrentStart.nValue == self.nGamer and mt.sum > sum or mt.sum < sum)):
                                                trump1,sum,elen,vz = i,mt.sum,mt.elen,mt.vzatok

                if self.level >= 2:
                        test_tricks = self.makeTestGame(trump1)
                        if trump2 != trump1:
                                test_tricks2 = self.makeTestGame(trump2)
                                if test_tricks2 > test_tricks:
                                        test_tricks = test_tricks2
                                        trump1 = trump2

                self.aCards.Sort()
                can_tricks = self.MastTable[0].vzatok
                if self.level >= 2 and test_tricks != can_tricks:
                        can_tricks = test_tricks
                min_tricks = int(self.GamesType/10)
                if can_tricks < min_tricks:
                        can_tricks = min_tricks
                game = can_tricks*10 + trump1
                if self.GamesType != undefined:
                        if game < self.GamesType:
                                if trump2 >= self.GamesType%10 and can_tricks == min_tricks:
                                        game = can_tricks*10 + trump2
                                else:
                                        game = (min_tricks+1)*10 + trump1
                self.GamesType = game
                return self.GamesType

        def makemove(self,lMove,rMove,aLeftGamer=None,aRightGamer=None):
                if aRightGamer:
                        global lGamer, rGamer, Gamer, Partner
                        lGamer = aLeftGamer
                        rGamer = aRightGamer
                        if aLeftGamer.GamesType > pas:
                                Gamer,Partner = aLeftGamer,aRightGamer
                        elif aRightGamer.GamesType > pas:
                                Gamer,Partner = aRightGamer,aLeftGamer
                        RetVal = None
                        if lMove is None and rMove is None:
                                if self.GamesType == pas or self.GamesType == vist:
                                        RetVal = self.MyVist1(aLeftGamer,aRightGamer)
                                elif self.GamesType == g86catch:
                                        RetVal = self.MiserCatch1(aLeftGamer,aRightGamer)
                                elif self.GamesType == g86:
                                        RetVal = self.Miser1(aLeftGamer,aRightGamer)
                                elif self.GamesType == raspas:
                                        RetVal = self.MyPas1(rMove,aLeftGamer,aRightGamer)
                                else:
                                        RetVal = self.MyGame1(aLeftGamer,aRightGamer)
                        if lMove is None and rMove:
                                if self.GamesType == pas or self.GamesType == vist:
                                        RetVal = self.MyVist2(rMove,aLeftGamer,aRightGamer)
                                elif self.GamesType == g86catch:
                                        RetVal = self.MiserCatch2(rMove,aLeftGamer,aRightGamer)
                                elif self.GamesType == g86:
                                        RetVal = self.Miser2(rMove,aLeftGamer,aRightGamer)
                                elif self.GamesType == raspas:
                                        RetVal = self.MyPas2(rMove,aLeftGamer,aRightGamer)
                                else:
                                        RetVal = self.MyGame2(rMove,aLeftGamer,aRightGamer)
                        if lMove and rMove:
                                if self.GamesType == pas or self.GamesType == vist:
                                        RetVal = self.MyVist3(lMove,rMove,aLeftGamer,aRightGamer)
                                elif self.GamesType == g86catch:
                                        RetVal = self.MiserCatch3(lMove,rMove,aLeftGamer,aRightGamer)
                                elif self.GamesType == g86:
                                        RetVal = self.Miser3(lMove,rMove,aLeftGamer,aRightGamer)
                                elif self.GamesType == raspas:
                                        RetVal = self.MyPas3(lMove,rMove,aLeftGamer,aRightGamer)
                                else:
                                        RetVal = self.MyGame3(lMove,rMove,aLeftGamer,aRightGamer)
                        #self.aCards.Remove(RetVal)
                        #self.aCardsOut.Insert(RetVal)
                        lGamer = rGamer = None
                        Partner = Gamer = None
                        #print self
                        return RetVal

                if not aLeftGamer is None:
                        MaxGame,HaveAVist,nGamerVist = lMove,rMove,aLeftGamer
                        opt = TGamer.gui.opt
                        if MaxGame == g86: # miser
                                Answer = g86catch
                        elif MaxGame == g61 and opt[stalingrad]: # Stalingrad
                                Answer = vist
                        else:
                                #MyMaxGame = self.makemove4out()
                                #vz = MyMaxGame/10
                                if self.level >= 2 and self.vzatok >= 0:
                                        vz = self.vzatok
                                else:
                                        vz = self.vzatok4vist()
                                need_vz = nGetMinCard4Vist(MaxGame)
                                min_vz = MaxGame < g91 and int(need_vz/2) or need_vz
#                               if HaveAVist != vist and vz >= min_vz:
#                                       Answer = vist
#                               else:
#                                       Answer = pas
#                               if HaveAVist == pas and vz < min_vz:
#                                       Answer = pas
                                if need_vz > 0 and MaxGame < g101:
                                        # LEVEL Hight
                                        if self.level >= 2:
                                                dt = TGamer.dt
                                                counter = Tncounter(self.nGamer,1,3)
                                                left = dt.Gamer(counter.next())
                                                right = dt.Gamer(counter.next())
                                                nap = left.GamesType == MaxGame and right or left
                                                if self.level >= 2 and nap.vzatok >= 0:
                                                        nap_vz = nap.vzatok
                                                else:
                                                        nap_vz = nap.vzatok4vist()
                                                if vz + nap_vz < need_vz:
                                                        Answer = pas
                                                else:
                                                        Answer = vz >= min_vz and vist or pas
                                        else:
                                                Answer = vz >= min_vz and vist or pas
                                        if Answer == vist and HaveAVist == vist and not opt[greedywhist]:
                                                Answer = pas
                                        if need_vz > 1 and Answer == pas and nGamerVist and HaveAVist == pas and opt[halfwhist]:
                                                Answer = halfvist
                                else:
                                        # g10x                                  
                                        dt = TGamer.dt
                                        trumps = self.MastTable[dt.Trump]                                        
                                        tp = self.aCards.Exist(A,1)
                                        tt = self.aCards.Exist(A,2)
                                        tb = self.aCards.Exist(A,3)
                                        tc = self.aCards.Exist(A,4)
                                        kp = self.aCards.Exist(K,1)
                                        kt = self.aCards.Exist(K,2)
                                        kb = self.aCards.Exist(K,3)
                                        kc = self.aCards.Exist(K,4)
                                        # 10 in suit
                                        if MaxGame >= g101 and MaxGame <= g104:
                                                # A legit trick in the trump suit (both vzatok4vist and vzatok4game functions are considered, since when only vzatok4vist is used, for some reason, both partners pass when each of them has 4 trumps)
                                                if trumps.vz23 >= 1 or trumps.vzatok >= 1:
                                                        Answer = vist
                                                # At least 3 Aces in one hand                            
                                                elif sum (1 for i in [tp, tt, tb, tc] if i != None) > 2:
                                                        Answer = vist                                                
                                                else:
                                                        Answer = pas
                                        # 10NT
                                        elif MaxGame == g105:
                                                # At least 3 Aces in one hand
                                                if sum (1 for i in [tp, tt, tb, tc] if i != None) > 2:
                                                        Answer = vist
                                                # The first move in the play belongs to an Ace holder 
                                                elif TGamer.dt.nCurrentStart.nValue == self.nGamer and sum (1 for i in [tp, tt, tb, tc] if i != None) > 0:
                                                        Answer = vist
                                                # The first move in the play belongs to the player who passed, while the second hand has an Ace in any suit and no more than 5 cards in total in that suit (so that the passed player has a lead in the suit)
                                                elif HaveAVist == pas and TGamer.dt.nCurrentStart.nValue == aLeftGamer and sum (1 for i in [tp, tt, tb, tc] if i != None) > 0:
                                                        if tp != None and self.MastTable[1].len <= 5 or tt != None and self.MastTable[2].len <= 5 or tb != None and self.MastTable[3].len <= 5 or tc != None and self.MastTable[4].len <= 5:
                                                                Answer = vist
                                                        else:
                                                                Answer = pas
                                                # Tricks in each suit
                                                elif self.MastTable[1].vzatok > 0 and self.MastTable[2].vzatok > 0 and self.MastTable[3].vzatok > 0 and self.MastTable[4].vzatok > 0:
                                                        Answer = vist
                                                else:
                                                        Answer = pas
                                        # Any 10 contract: if a whist player has the hand T--, T--, Kx-, x or better (the case when he gets 1 or 2 tricks with the probability >66%, so that the mathematical expectation is positive)
                                        elif MaxGame >= g101 and MaxGame <= g105:
                                                if tp != None and tt != None and kb != None and self.MastTable[3].len >= 2 and self.MastTable[4].len >= 1:
                                                        Answer = vist
                                                elif tp != None and tt != None and kc != None and self.MastTable[4].len >= 2 and self.MastTable[3].len >= 1:
                                                        Answer = vist
                                                elif tp != None and tb != None and kt != None and self.MastTable[2].len >= 2 and self.MastTable[4].len >= 1:
                                                        Answer = vist
                                                elif tp != None and tb != None and kc != None and self.MastTable[4].len >= 2 and self.MastTable[2].len >= 1:
                                                        Answer = vist
                                                elif tp != None and tc != None and kt != None and self.MastTable[2].len >= 2 and self.MastTable[3].len >= 1:
                                                        Answer = vist
                                                elif tp != None and tc != None and kb != None and self.MastTable[3].len >= 2 and self.MastTable[2].len >= 1:
                                                        Answer = vist
                                                elif tt != None and tb != None and kp != None and self.MastTable[1].len >= 2 and self.MastTable[4].len >= 1:
                                                        Answer = vist
                                                elif tt != None and tb != None and kc != None and self.MastTable[4].len >= 2 and self.MastTable[1].len >= 1:
                                                        Answer = vist
                                                elif tt != None and tc != None and kp != None and self.MastTable[1].len >= 2 and self.MastTable[3].len >= 1:
                                                        Answer = vist
                                                elif tt != None and tc != None and kb != None and self.MastTable[3].len >= 2 and self.MastTable[1].len >= 1:
                                                        Answer = vist
                                                elif tb != None and tc != None and kp != None and self.MastTable[1].len >= 2 and self.MastTable[2].len >= 1:
                                                        Answer = vist
                                                elif tb != None and tc != None and kt != None and self.MastTable[2].len >= 2 and self.MastTable[1].len >= 1:
                                                        Answer = vist
                                                else:
                                                        Answer = pas                                        
                                        else:
                                                Answer = pas
                                        if Answer == vist and HaveAVist == vist and not opt[greedywhist]:
                                                Answer = pas                                    
                        self.GamesType = Answer
                        return Answer

                if self.GamesType != pas:
                        MGT = max(lMove,rMove)
                        if self.GamesType == undefined:
                                if self.level >= 3:
                                        # MakeMastTable hack - reset and restore GamesType of left and right gamers
                                        dt = TGamer.dt
                                        counter = Tncounter(self.nGamer,1,3)
                                        left = dt.Gamer(counter.next())
                                        right = dt.Gamer(counter.next())
                                        save_left = left.GamesType
                                        save_right = right.GamesType
                                        left.GamesType = undefined
                                        right.GamesType = undefined
                                        ##########################
                                        tmpList = TCardList(10)
                                        tmpList.Assign(self.aCards)
                                        self.aCards.Insert(TGamer.dt.Coloda.At(30))
                                        self.aCards.Insert(TGamer.dt.Coloda.At(31))
                                        self.makeout4game()
                                        self.aCards.Assign(tmpList)
                                        self.aOut.RemoveAll()
                                        ##########################
                                        left.GamesType = save_left
                                        right.GamesType = save_right
                                else:
                                        nMaxMast = self.makemove4out(1)
                                        self.GamesType = self.MastTable[0].vzatok * 10 + nMaxMast
                                self.MaxGame = self.GamesType
                        self.GamesType = self.MaxGame
                        #if rMove == pas or rMove == undefined and lMove == pas or lMove == undefined:
                        if MGT <= pas:
                                #print "two pass or undef"
                                start = self.MinTricks()
                                min_vz = self.level >= 3 and start or (start-1)
                                #min_vz = 11
                                if int(self.GamesType/10) >= min_vz:
                                        if self.Check4Miser():
                                                self.GamesType = g86
                                        else:
                                                #self.GamesType = g61
                                                self.GamesType = start*10+1
                                else:
                                        if self.Check4Miser():
                                                self.GamesType = g86
                                        else:
                                                self.GamesType = pas
                        #elif self.GamesType > MGT:
                        #elif self.GamesType > MGT or rMove/lMove == pas and self.GamesType == MGT:
                        elif self.GamesType >= MGT and MGT != g86:
                                nRight = self.nGamer == 1 and 3 or (self.nGamer == 2 and 1 or 2)
                                nLeft = self.nGamer == 1 and 2 or (self.nGamer == 2 and 3 or 1)
                                #print "my game is:", self.GamesType, "MGT",MGT,'rMove',rMove,'lMove',lMove
                                #print "my game is:", self.GamesType, "MGT",MGT, TGamer.dt.nCurrentStart.nValue, self.nGamer
                                #if the first hand and rMove/lMove == pas or being the second hand while the first one passed:                                
                                if TGamer.dt.nCurrentStart.nValue == self.nGamer and (rMove == pas or lMove == pas) or rMove == pas and TGamer.dt.nCurrentStart.nValue == nRight:                                        
                                        self.GamesType = MGT
                                else:
                                        self.GamesType = NextGame(MGT)
                        else:
                                #print "i'm pass"
                                self.GamesType = pas
                return self.GamesType

        def MinTricks(self):
                tricks = 6
                pe = TGamer.gui.opt[pasexit]
                if TPlScore.rcnt > 1 and pe:
                        tricks += 1
                        if TPlScore.rcnt > 2 and pe > 1: 
                                tricks += 1
                return tricks

        def MiserMast(self,mast,check=False):
                # Test "clear"
                if self.aCards.MiserMast(mast):
                        return True
                if check:
                        # Test if self first move and have othod in this mast
                        mt = self.MastTable[mast]
                        if mt.len == 1 and mt.othodov and TGamer.dt.nCurrentStart.nValue == self.nGamer:
                                for m in (1,2,3,4):
                                        if m != mast and not self.aCards.MiserMast(mast):
                                                return False
                                return True
                return False

        def Check4Miser(self):
                for m in (1,2,3,4):
                        if not self.MiserMast(m,True):
                                return False
                return True

        def vzatok4game(self,mast=0):
                return self.MastTable[mast].vzatok

        def vzatok4vist(self,mast=0):
                return self.MastTable[mast].vz23

        def MyPas1(self,rMove,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                if rMove:
                        aTmpList = TCardList(MAXMASTLEN)
                        aTmpList.AssignMast(self.aCards,rMove.CMast)
                        aStackStore = self.aCards
                        self.aCards = aTmpList
                if tmpGamesType == raspas or tmpGamesType == g86:
                        RetVal = self.GetMaxCardWithoutPere()
                        if RetVal:
                                if aLeftGamer.GetAll(RetVal.CMast) == 0 and aRightGamer.GetAll(RetVal.CMast) == 0:
                                        RetVal = None
                        if not RetVal:
                                #RetVal = self.GetMaxCardPere() or self.GetMinCardWithoutVz() or self.GetMin()
                                RetVal = self.Othod(True) or self.GetMaxCardPere() or self.GetMinCardWithoutVz() or self.GetMin()
                if rMove:
                        self.aCards = aStackStore
                self.GamesType = tmpGamesType
                return RetVal

        def MyPas2(self,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                mast = aRightCard.CMast
                #print "MyPas2 game", tmpGamesType
                if tmpGamesType == raspas or tmpGamesType == g86:
                        RetVal = self.GetMax(mast)
                        if not RetVal:
                                RetVal = self.GetMaxCardWithoutPere() or self.GetMaxCardPere() or self.GetMinCardWithoutVz() or self.GetMin()
                        else:
                                if aLeftGamer.GetAll(mast):
                                        #RetVal = self.aCards.LessThan(aLeftGamer.GetMax(mast)) or self.GetMax(mast)
                                        RetVal = self.aCards.LessThan(aRightCard) or self.aCards.LessThan(aLeftGamer.GetMax(mast)) or RetVal
                                else:
                                        #RetVal = self.aCards.LessThan(aRightCard) or self.GetMax(mast)
                                        RetVal = self.aCards.LessThan(aRightCard) or RetVal
                self.GamesType = tmpGamesType
                return RetVal

        def MyPas3(self,aLeftCard,aRightCard,aLeftGamer,aRightGamer):
                RetVal = None
                tmpGamesType = self.GamesType
                if self.GetAll(aLeftCard.CMast):
                        if aLeftCard.CMast == aRightCard.CMast:
                                if aRightCard > aLeftCard:
                                        RetVal = self.aCards.LessThan(aRightCard)
                                else:
                                        RetVal = self.aCards.LessThan(aLeftCard)
                        else:
                                RetVal = self.aCards.LessThan(aLeftCard)
                        if not RetVal:
                                RetVal = self.GetMax(aLeftCard.CMast)
                else:
                        RetVal = self.GetMaxCardWithoutPere() or self.GetMaxCardPere() or self.GetMinCardWithoutVz() or self.GetMin()
                self.GamesType = tmpGamesType
                return RetVal

        def GetMin(self,mast=0):
                return self.MastTable[mast].min

        def GetMax(self,mast=0):
                return self.MastTable[mast].max

        def GetAll(self,mast=0):
                return self.MastTable[mast].len

        def GetMinMaxAll(self,mast):
                mt = self.MastTable[mast]
                return (mt.min, mt.max, mt.len)

        def makemoveL(self,lMove,rMove,aLeftGamer,aRightGamer):
                RetVal = self.makemove(lMove,rMove,aLeftGamer,aRightGamer)
                self.aCards.Remove(RetVal)
                self.aCardsOut.Insert(RetVal)
                return RetVal

        def makeTestGame(self,trump=None):
                dt = TGamer.dt
                dt.CurrentGame = trump and 60+trump or g86
                dt.Trump = trump

                save_Cards = [None,TCardList(12),TCardList(12),TCardList(12)] 
                #save_CardsOut = [None,TCardList(12),TCardList(12),TCardList(12)] 
                save_GetsCard = [None,0,0,0] 
                save_GamesType = [None,0,0,0] 
                for i in (1,2,3):
                        gamer = dt.Gamer(i)
                        save_Cards[i].Assign(gamer.aCards)
                        #save_CardsOut[i].Assign(gamer.aCardsOut)
                        save_GamesType[i] = gamer.GamesType
                        if gamer == self:
                                gamer.GamesType = dt.CurrentGame
                        elif dt.CurrentGame != g86:
                                gamer.GamesType = vist
                        else:
                                gamer.GamesType = g86catch

                dt.MkMastTables(1)
                t = time.time()
                trump = dt.CurrentGame%10
                counter = Tncounter(0,1,3)
                counter.copy(dt.nCurrentStart)
                for i in range(1,11):
                        tmpCard1 = None
                        if TGamer.gui.opt[pastalon] and dt.CurrentGame == raspas and 1 <= i <= 3:
                                counter.copy(dt.nCurrentStart)
                        if TGamer.gui.opt[pastalon] and dt.CurrentGame == raspas and 1 <= i <= 2:
                                tmpCard1 = TCard(1,dt.Coloda.At(29+i).CMast)
                        Card1 = dt.Gamer(counter.nValue).makemoveL(None,tmpCard1,dt.Gamer(NextGamer(counter)),dt.Gamer(PrevGamer(counter)))
                        if tmpCard1 and tmpCard1.CMast != Card1.CMast:
                                Card1 = tmpCard1
                        prev = counter.nValue
                        counter.next()
                        Card2 = dt.Gamer(counter.nValue).makemoveL(None,Card1,dt.Gamer(NextGamer(counter)),dt.Gamer(prev))
                        if Card1 == tmpCard1 and Card2.CMast != tmpCard1.CMast:
                                Card2 = tmpCard1
                        prev = counter.nValue
                        counter.next()
                        Card3 = dt.Gamer(counter.nValue).makemoveL(Card1,Card2,dt.Gamer(NextGamer(counter)),dt.Gamer(prev))
                        counter.next()
                        nPl = dt.nPlayerTakeCards(Card1,Card2,Card3,trump)-1
                        while nPl:
                                counter.next()
                                nPl -= 1
                        dt.Gamer(counter.nValue).nGetsCard += 1
                        dt.MkMastTables(1)

                for i in (1,2,3):
                        gamer = dt.Gamer(i)
                        gamer.aCards.Assign(save_Cards[i])
                        gamer.GamesType = save_GamesType[i]
                        gamer.aCardsOut.RemoveAll()
                        gamer.vzatok = gamer.nGetsCard
                        gamer.nGetsCard = 0

                dt.MkMastTables()
                return self.vzatok


#       def GetBackSnos(self):
#               for i in (0,2):
#                       if self.aCardsOut.At(i):
#                               self.aCards.Insert(self.aCardsOut.At(i))
#               self.aCardsOut.RemoveAll()

if __name__ == '__main__':
        pass
