#
# PyPref - Preference game for Windows, *NIX and Pocket PC
# This source code is based on kpref by Azarniy I.V.
# and OpenPref (http://openpref.narod.ru)
#
# Author (version 2.0): Alexander aka amigo <amigo12@newmail.ru> - Aug 2007
# Versions 2.1-2.34: Vadim Zapletin <preference.gixx@mail.ru> - Feb-Mar 2018
# License: GNU GPL
#

#import pdb
import sys

from prefgame.card import *
from prefgame.ctlist import *
from prefgame.coloda import *
from prefgame.gamer import *
from prefgame.ncounter import *

def eot(game):
        return game[1] != undefined and game[2] != undefined and game[3] != undefined \
                and ((game[1] == pas and 1 or 0) + (game[2] == pas and 1 or 0) + (game[3] == pas and 1 or 0)) >= 2

class TDeskTop:

        def __init__(self,guiobj):
                #self.CardOnDesk = [TCard() for x in range(0,4)]
                #self.finish = False
                global gui
                gui = guiobj
                self.mode = halt
                self.CardOnDesk = [None,None,None,None]
                #self.Coloda = TColoda()
                self.Coloda = None
                self.Gamers = Tclist(4)
                self.nCurrentStart = Tncounter(2,1,3)
                self.nCurrentMove = Tncounter(2,1,3)
                self.Gamers.Insert(TGamer(0,self,gui))
                #self.Gamers.Insert(1)
                self.Gamers.Insert(TGamer(1))
                self.Gamers.Insert(TGamer(2))
                self.Gamers.Insert(TGamer(3))
                self.nBuletScore = None
                self.CurrentGame = None
                self.Trump = None

        def CloseBullet(self):
                         
                cnt = Tncounter(1,1,3)
                m,b,lv,rv = 0,1,2,3
                R = [[0,0,0,0] for x in range(0,4)]
                for i in (1,2,3):
                        g = self.Gamer(i)
                        r = R[i]
                        r[m]= g.aScore.nGetMount()
                        r[b] = g.aScore.nGetBull()
                        r[lv] = g.aScore.nGetLeftVists()
                        r[rv] = g.aScore.nGetRightVists()
                for i in (1,2,3):
                        r = R[i]
                        if gui.opt[scorerules] == Peter:
                                r[lv] += r[b]*2*10//3
                        else:
                                r[lv] += r[b]*10//3       
                        if gui.opt[scorerules] == Peter:      
                                r[rv] += r[b]*2*10//3
                        else:        
                                r[rv] += r[b]*10//3        
                for i in (1,2,3):
                        cnt.nValue = i     
                        cnt.next()
                        R[cnt.nValue][rv] += R[i][m]*10//3
                        cnt.next()
                        R[cnt.nValue][lv] += R[i][m]*10//3
                for i in (1,2,3):
                        cnt.nValue = i
                        cnt.next()
                        i1 = cnt.nValue
                        cnt.next()
                        i2 = cnt.nValue
                        self.Gamer(i).aScore.Vists = R[i][lv] + R[i][rv] - R[i1][rv] - R[i2][lv]
                                        
        def Setup(self):
                opt = gui.opt
                # Levels
                self.Gamer(2).level = opt[leftlvl]
                self.Gamer(3).level = opt[rightlvl]
                self.Gamer(1).level = max(opt[leftlvl],opt[rightlvl])
                # Other
                self.Gamer(0).aScore.Setup(opt)

        def PipeMakemove(self,lMove,rMove):
                return self.Gamer(self.nCurrentMove.nValue).makemove(lMove,rMove,\
                                                                self.Gamer(NextGamer(self.nCurrentMove)),self.Gamer(PrevGamer(self.nCurrentMove)))

        def ControllingMakemove(self,lMove,rMove):
                gamer = self.Gamer(self.nCurrentMove.nValue)
                if gamer.human and self.mode != demo:
                        RetVal = gui.MakeMove(gamer,(lMove or rMove),hint=(gui.opt[hintcard] and self.PipeMakemove(lMove,rMove) or None))
                        if self.mode == halt:
                                return
                else:
                        RetVal = self.PipeMakemove(lMove,rMove)
                        if self.mode == run and gui.StopGame():
                                return
                gamer.aCards.Remove(RetVal)
                gamer.aCardsOut.Insert(RetVal)
                return RetVal

        def TorgMakemove(self,gamer,lGame,rGame):
                if gamer.human and self.mode != demo:
                        if gamer.GamesType == pas:
                                return gamer.GamesType
                        hint = None
                        if gui.opt[hintgame]:
                                save = gamer.GamesType
                                hint = gamer.makemove(lGame,rGame)
                                gamer.GamesType = save
                        #gamer.GamesType = gui.MakeGame(gamer,max(lGame,rGame),hint=hint,rightgame=rGame)
                        gamer.GamesType = gui.MakeGame(gamer,max(lGame,rGame),hint=hint)
                        if self.mode == halt:
                                return
                        return gamer.GamesType
                else:
                        return gamer.makemove(lGame,rGame)

        def MakeoutOrMove(self,gamer,game=None,left=None,right=None):
                        if game is not None and game >= g101 and gui.opt[check10]:
                                gamer.GamesType = vist
                                return gamer.GamesType
                        if gamer.human and self.mode != demo:
                                if game == g61 and gui.opt[stalingrad]:
                                        gamer.GamesType = vist
                                elif game == g86:
                                        gamer.GamesType = g86catch
                                else:
                                        if game:
                                                gamer.GamesType = gui.MakeGame(gamer,game,True,hint=(gui.opt[hintgame] and gamer.makemove(game,left,right) or None))
                                        else:
                                                game = gamer.GamesType
                                                if gui.opt[hintdiscard]:
                                                        if game == g86:
                                                                gamer.makeout4miser()
                                                        else:
                                                                gamer.makeout4game()
                                                        hint,hint1 = gamer.aOut.At(0),gamer.aOut.At(1)
                                                        for i in (0,1):
                                                                card = gamer.aOut.At(0)
                                                                gamer.aCards.Insert(card)
                                                                gamer.aOut.Remove(card)
                                                        gamer.aCards.Sort()
                                                        gamer.GamesType = game
                                                else:
                                                        hint = hint1 = None
                                                #while gamer.aOut.Count() < 2:
                                                #pdb.set_trace()
                                                while True:
                                                #while gui.opt[confirm] or gamer.aOut.Count() < 2:
                                                        card = gui.MakeMove(gamer,hint=hint,hint1=hint1,out=gamer.aOut.Count())
                                                        if self.mode == halt:
                                                                return
                                                        if card:
                                                                gamer.aCards.Remove(card)
                                                                gamer.aOut.Insert(card)
                                                        elif card is None:
                                                                i = gamer.aOut.Count()-1
                                                                if i >= 0:
                                                                        card = gamer.aOut.At(i)
                                                                        gamer.aOut.Remove(card)
                                                                        gamer.aCards.Insert(card)
                                                                        gamer.aCards.Sort()
                                                        else:
                                                                break
                                                        gui.ShowHand(gamer)
                                                        gui.ShowPrikup(gamer.aOut.Count())
                                                gui.ShowPrikup(0)
                                                self.MkMastTables()
                                                #gamer.GamesType = gui.MakeGame(gamer,hint=(gui.opt[hintgame] and gamer.makemove4out() or None))
                                                gamer.GamesType = gui.MakeGame(gamer,hint=(gui.opt[hintgame] and gamer.MaxGame or None))
                                                if gamer.GamesType == bez3:
                                                        gamer.GamesType = game
                                                        return bez3
                                        if self.mode == halt:
                                                return
                                return gamer.GamesType
                        else:
                                return gamer.makemove(game,left,right)

        def EndOfGame(self):
                limit = self.nBulletScore
                if gui.opt[scorerules] == Peter:
                        limit *= 3
                        return (self.Gamer(1).aScore.nGetBull() + self.Gamer(2).aScore.nGetBull() + self.Gamer(3).aScore.nGetBull() >= limit)
                else:
                        return (self.Gamer(1).aScore.nGetBull() >= limit and self.Gamer(2).aScore.nGetBull() >= limit and self.Gamer(3).aScore.nGetBull() >= limit)

        def RunGame(self,mode=run,loaded=None):
                #global nBulletScore
                self.mode = mode
                GamesType = [None,None,None,None]
                #nBulletScore = self.nBulletScore
                for i in (1,2,3):
                        if not loaded:
                                self.Gamer(i).aScore = TPlScore()
                        self.Gamer(i).aScore.nBulletScore = self.nBulletScore

                self.Setup()
#               # Levels
#               self.Gamer(2).level = gui.opt[leftlvl]
#               self.Gamer(3).level = gui.opt[rightlvl]
#               self.Gamer(1).level = max(gui.opt[leftlvl],gui.opt[rightlvl])

                while not self.EndOfGame():
                        if self.mode == halt:
                                return
                        GamersCounter = Tncounter(1,1,3)
                        nGamerNumber = 0
                        nPasCounter = 0                 
                        for i in range(0,4):
                                GamesType[i] = undefined
                                self.CardOnDesk[i] = None

                        self.CurrentGame = undefined
                        self.Coloda = Coloda = TColoda(CARDINCOLODA)
                        Coloda.Mix()
                        for i in (1,2,3):
                                self.Gamer(i).set0()

                        # Sdacha
                        gui.Clear()
                        for i in range(0,CARDINCOLODA-2):
                                gamer = self.Gamer(GamersCounter.nValue)
                                gamer.aCards.Insert(Coloda.At(i))
                                if i == 11:
                                        gui.ShowPrikup(2)
                                if i and gamer.aCards.Count()%2 == 0:
                                        gui.ShowHand(gamer)
                                        gui.sleep(0.1)
                                        if gui.StopGame():
                                                return
                                GamersCounter.next()
                        self.Rasklad(Coloda)

                        self.Trump = 0
                        self.Gamer(1).human = True
                        self.Gamer(1).closed = False
                        GamersCounter.copy(self.nCurrentStart)
                        # Show cards
                        for i in (1,2,3):
                                self.Gamer(i).aCards.Sort()
                                if i == 1:
                                        gui.ShowHand(self.Gamer(i))
                                gui.ShowGame(self.Gamer(GamersCounter.nValue),None,i)
                                GamersCounter.next()
                        GamersCounter.copy(self.nCurrentStart)
                        # Torg
                        self.MkMastTables()
                        while True:
                                if GamesType[1] != pas:
                                        #GamesType[1] = self.Gamer(GamersCounter.nValue).makemove(GamesType[2],GamesType[3])
                                        GamesType[1] = self.TorgMakemove(self.Gamer(GamersCounter.nValue),GamesType[2],GamesType[3])
                                        if self.mode == halt:
                                                return
                                #---------------- feal ------------------------------------
                                gui.ShowGame(self.Gamer(GamersCounter.nValue),GamesType[1],1)
                                #----------------------------------------------------------
                                GamersCounter.next()
                                if eot(GamesType):
                                        break
                                if GamesType[2] != pas:
                                        GamesType[2] = self.TorgMakemove(self.Gamer(GamersCounter.nValue),GamesType[3],GamesType[1])
                                        if self.mode == halt:
                                                return
                                #---------------- feal ------------------------------------
                                gui.ShowGame(self.Gamer(GamersCounter.nValue),GamesType[2],1)
                                #----------------------------------------------------------
                                GamersCounter.next()
                                if eot(GamesType):
                                        break
                                if GamesType[3] != pas:
                                        GamesType[3] = self.TorgMakemove(self.Gamer(GamersCounter.nValue),GamesType[1],GamesType[2])
                                        if self.mode == halt:
                                                return
                                #---------------- feal ------------------------------------
                                gui.ShowGame(self.Gamer(GamersCounter.nValue),GamesType[3],1)
                                #----------------------------------------------------------
                                GamersCounter.next()
                                if eot(GamesType):
                                        break

                        # What maximum game?
                        for i in (1,2,3):
                                GamesType[0] = max(GamesType[0],GamesType[i])

                        NeedGame = True
                        if GamesType[0] == pas:
                                # raspass
                                #nRaspasCnt += 1
                                self.CurrentGame = raspas
                                for i in (1,2,3):
                                        self.Gamer(i).GamesType = raspas
                                        gui.ShowGame(self.Gamer(i),pas)
                                self.MkMastTables()
                                if not gui.opt[pastalon]:
                                        gui.ShowPrikup(0)
                        else:
                                # game
                                #nRaspasCnt = 0
                                #--------------- feal ----------------------------------
                                # Show Pass before take prikup
                                #gui.sleep(1)
                                for i in (1,2,3):
                                        gamer = self.Gamer(i)
                                        if gamer.GamesType != GamesType[0]:
                                                gui.ShowGame(gamer,undefined)
                                #-------------------------------------------------------
                                for i in (1,2,3):
                                        gamer = self.Gamer(i)
                                        if gamer.GamesType == GamesType[0]:
                                                nPasCounter = 0
                                                tmpGamersCounter = Tncounter(1,3)
                                                PasOrVist = nPasOrVist = 0
                                                self.CardOnDesk[2] = Coloda.At(30)
                                                self.CardOnDesk[3] = Coloda.At(31)
                                                gui.ShowPrikup(2,self.CardOnDesk[2],self.CardOnDesk[3])
                                                if self.mode == halt:
                                                        return
                                                #---------------- feal ------------------------------------
                                                gui.ShowPrikup(0)
                                                #----------------------------------------------------------
                                                gamer.aCards.Insert(Coloda.At(30))
                                                gamer.aCards.Insert(Coloda.At(31))
                                                gamer.aCards.Sort()
                                                gui.ShowHand(gamer)
                                                nGamerNumber = gamer.nGamer
                                                #------------------------------
                                                #self.MkMastTables(1)
                                                #------------------------------
                                                if gamer.human and self.mode != demo:
                                                        self.CurrentGame = self.MakeoutOrMove(gamer)
                                                        if self.mode == halt:
                                                                return
                                                        if self.CurrentGame == bez3:
                                                                NeedGame = False
                                                                break
                                                elif gamer.GamesType != g86:
                                                        # not miser
                                                        self.nCurrentMove.nValue = i
                                                        self.CurrentGame = gamer.makeout4game()
                                                        if self.CurrentGame >= g101 and gui.opt[check10]:
                                                                gamer.aCards.Insert(gamer.aOut.At(0))
                                                                gamer.aCards.Insert(gamer.aOut.At(1))
                                                                gamer.aCards.Sort()
                                                                gamer.closed = False                                                            
                                                                gui.ShowGame(gamer,self.CurrentGame)                                                            
                                                                gui.ShowHand(gamer,-2)
                                                                gamer.aCards.Remove(gamer.aOut.At(0))
                                                                gamer.aCards.Remove(gamer.aOut.At(1))
                                                                gamer.aCards.Sort()
                                                else:
                                                        # miser - open all cards
                                                        gamer.closed = False
                                                        gui.ShowHand(gamer,-2)
                                                        gui.HitReturn(forcekey=True)
                                                        gamer.closed = True
                                                        gui.ShowHand(gamer,-2)
                                                        self.CurrentGame = gamer.makeout4miser()
                                                tmpGamersCounter.nValue = i

                                                gui.ShowHand(gamer)
                                                gui.ShowGame(gamer,self.CurrentGame)
                                                self.Trump = self.CurrentGame%10

                                                self.MkMastTables(1)

                                                # Pass or Vist
                                                tmpGamersCounter.next()
                                                HalfVistGamer = None
                                                while True:
                                                        PasOrVistGamers = self.Gamer(tmpGamersCounter.nValue)
                                                        PasOrVistGamers.GamesType = undefined
                                                        #PasOrVist = self.MakeoutOrMove(PasOrVistGamers,self.CurrentGame,pas,0)
                                                        PasOrVist = self.MakeoutOrMove(PasOrVistGamers,self.CurrentGame,(HalfVistGamer and halfvist or pas),0)
                                                        if self.mode == halt:
                                                                return
                                                        nPasOrVist = tmpGamersCounter.nValue
                                                        if PasOrVistGamers.GamesType == pas:
                                                                nPasCounter += 1
                                                        #---------------- feal ------------------------------------
                                                        gui.ShowGame(self.Gamer(tmpGamersCounter.nValue),PasOrVistGamers.GamesType)
                                                        #----------------------------------------------------------
                                                        if HalfVistGamer:
                                                                if PasOrVist == vist:
                                                                        HalfVistGamer.GamesType = pas
                                                                        HalfVistGamer.MaxGame = halfvist
                                                                        HalfVistGamer = None
                                                                break
                                                        if nPasCounter >= 2:
                                                                if PasOrVist == vist:
                                                                        nPasCounter = 1
                                                                break
                                                        tmpGamersCounter.next()
                                                        PasOrVistGamers = self.Gamer(tmpGamersCounter.nValue)
                                                        PasOrVistGamers.GamesType = undefined
                                                        #PasOrVistGamers.makemove(self.CurrentGame,PasOrVist,nPasOrVist)
                                                        self.MakeoutOrMove(PasOrVistGamers,self.CurrentGame,PasOrVist,nPasOrVist)
                                                        if self.mode == halt:
                                                                return
                                                        #---------------- feal ------------------------------------
                                                        gui.ShowGame(self.Gamer(tmpGamersCounter.nValue),PasOrVistGamers.GamesType)
                                                        #----------------------------------------------------------
                                                        if PasOrVistGamers.GamesType == pas:
                                                                nPasCounter += 1
                                                                if nPasCounter == 2 and gui.opt[halfwhist]:
                                                                        tmpGamersCounter.prev()
                                                                        continue                                                                                                                                                                                        
                                                                if nPasCounter == 2 and gui.opt[whistpas]:
                                                                        gamer.nGetsCard = nGetGameCard(gamer.GamesType)                                                                        
                                                        elif PasOrVistGamers.GamesType == halfvist:
                                                                HalfVistGamer = PasOrVistGamers
                                                                tmpGamersCounter.prev()
                                                                continue
                                                        break

                                                if nPasCounter >= 2:
                                                        # Two pass
                                                        gamer.nGetsCard = nGetGameCard(gamer.GamesType)
                                                        if HalfVistGamer:
                                                                HalfVistGamer.nGetsCard = 10-gamer.nGetsCard
                                                        NeedGame = False
                                                else:
                                                        # 'in light' or 'in dark'
                                                        for n in (1,2,3):
                                                                gamer = self.Gamer(n)
                                                                if n == 1:
                                                                        if gamer.GamesType == pas:
                                                                                gamer.human = False
                                                                elif nPasCounter or self.CurrentGame == g86 or self.CurrentGame >= g101 and gui.opt[check10]:
                                                                        if gamer.GamesType == pas or gamer.GamesType == vist or gamer.GamesType == g86catch:
                                                                                if gamer.GamesType == pas and self.Gamer(1).GamesType == vist and not gui.AskOpen():
                                                                                        continue
                                                                                gamer.opened = self.opened = True
                                                                                gamer.closed = False
                                                                                gui.ShowHand(gamer,-2)
                                                                        if gamer.GamesType == pas and self.Gamer(1).GamesType == vist:
                                                                                gamer.human = True
                                                break

                        #--------------- feal ----------------------------------
                        # Clean order of move numbers
                        for i in (1,2,3):
                                gui.ShowGame(self.Gamer(i),None,-1)
                        #-------------------------------------------------------
                        if NeedGame:
                                self.nCurrentMove.copy(self.nCurrentStart)
                                for i in range(1,11):
                                        self.CardOnDesk[0] = self.CardOnDesk[1] = self.CardOnDesk[2] = self.CardOnDesk[3] = None
                                        if gui.opt[pastalon] and self.CurrentGame == raspas and 1 <= i <= 3:
                                                self.nCurrentMove.copy(self.nCurrentStart)
                                                self.Trump = None
                                        tmpCard1 = None
                                        if gui.opt[pastalon] and self.CurrentGame == raspas and 1 <= i <= 2:
                                                self.Trump = None
                                                tmp4show = Coloda.At(29+i)
                                                #---------------- feal ------------------------------------
                                                gui.ShowPrikup(3-i,tmp4show)
                                                #----------------------------------------------------------
                                                #Card1 = self.ControllingMakemove(None,tmp4rpas)
                                                Card1 = self.ControllingMakemove(None,tmp4show)
                                                if Card1.CMast != tmp4show.CMast:
                                                        tmpCard1 = TCard(1,tmp4show.CMast)
                                        else:
                                                Card1 = self.ControllingMakemove(None,None)
                                        if self.mode == halt:
                                                return
                                        #---------------- feal ------------------------------------
                                        gui.ShowMove(Card1,self.Gamer(self.nCurrentMove.nValue))
                                        #----------------------------------------------------------
                                        if tmpCard1 and tmpCard1.CMast != Card1.CMast:
                                                Card1 = tmpCard1
                                        self.nCurrentMove.next()
                                        Card2 = self.ControllingMakemove(None,Card1)
                                        if self.mode == halt:
                                                return
                                        #---------------- feal ------------------------------------
                                        gui.ShowMove(Card2,self.Gamer(self.nCurrentMove.nValue))
                                        #----------------------------------------------------------
                                        if Card1 == tmpCard1 and Card2.CMast != tmpCard1.CMast:
                                                Card2 = tmpCard1
                                        self.nCurrentMove.next()
                                        Card3 = self.ControllingMakemove(Card1,Card2)
                                        if self.mode == halt:
                                                return
                                        #---------------- feal ------------------------------------
                                        gui.ShowMove(Card3,self.Gamer(self.nCurrentMove.nValue))
                                        #----------------------------------------------------------
                                        self.nCurrentMove.next()
                                        nPl = self.nPlayerTakeCards(Card1,Card2,Card3,self.Trump)-1
                                        while nPl:
                                                self.nCurrentMove.next()
                                                nPl -= 1
                                        gamer = self.Gamers.At(self.nCurrentMove.nValue)
                                        gamer.nGetsCard += 1
                                        #---------------- feal ------------------------------------
                                        gui.ShowGame(gamer)
                                        #----------------------------------------------------------
                                        self.MkMastTables(1)

                        self.nCurrentStart.next()

                        # end of game - write scores
                        for i in (1,2,3):
                                self.Gamer(i).aScore.New = [0,0,0,0]
                        for i in (1,2,3):
                                g = self.Gamer(i)
                                Gamer = self.Gamer(nGamerNumber)
                                Val = g.aScore.AddRecords(self.CurrentGame,g.GamesType,(Gamer and Gamer.nGetsCard or 0),\
                                                                                                                                                g.nGetsCard,(Gamer and nGamerNumber or 0), i, 2-nPasCounter, self)
                                if Val:
                                        index = self.GetGamerWithMaxBullet()
                                        if index:
                                                tmp = Val
                                                Val = self.Gamer(index).aScore.AddBullet(Val)
                                                g.aScore.AddVist(index,i,tmp-Val)
                                                if Val:
                                                        index = self.GetGamerWithMaxBullet()
                                                        if index:
                                                                tmp = Val
                                                                Val = self.Gamer(index).aScore.AddBullet(Val)
                                                                g.aScore.AddVist(index,i,tmp-Val)
                                                                if Val:
                                                                        g.aScore.MountanDown(Val)
                                                        else:
                                                                g.aScore.MountanDown(Val)
                                        else:
                                                g.aScore.MountanDown(Val)

                        self.CloseBullet()
                        #---------------- feal ------------------------------------
                        gui.ShowPaper()

                        # Show rasklad
                        out = Tclist(2)
                        for i in (1,2,3):
                                gamer = self.Gamer(i)
                                if gamer.aOut.Count():
                                        out.Insert(gamer.aOut.At(0))
                                        out.Insert(gamer.aOut.At(1))
                                if gamer.aCardsOut.Count():
                                        gamer.aCards.Assign(gamer.aCardsOut)
                                gamer.aCards.Sort()
                                if gamer.closed:
                                        gamer.closed = False
                                        gui.ShowHand(gamer,-2)
                                else:
                                        gui.ShowHand(gamer)
                        if out.Count() == 0:
                                out.Insert(Coloda.At(30))
                                out.Insert(Coloda.At(31))
                        gui.ShowPrikup(2,out.At(0),out.At(1))
                        #----------------------------------------------------------

        def GetGamerWithMaxBullet(self):
                Max = Cur = -1
                Ret = 0
                for i in (1,2,3):
                        Cur = self.Gamer(i).aScore.nGetBull()
                        if Max < Cur < self.nBulletScore:
                                Max = Cur
                                Ret = i
                return Ret

        def nPlayerTakeCards(self,c1,c2,c3,koz):
                Max = c1
                Ret = 1
                if Max.CMast == c2.CMast and Max.CName < c2.CName or Max.CMast != koz and c2.CMast == koz:
                        Max = c2
                        Ret = 2
                if Max.CMast == c3.CMast and Max.CName < c3.CName or Max.CMast != koz and c3.CMast == koz:
                        Ret = 3
                return Ret

        def Gamer(self,n):
                return self.Gamers.At(n)

        def Rasklad(self,coloda):
                try:
                        p,t,b,c = 1,2,3,4
                        #f = open('c:/ras')
                        f = open('./ras')
                        carr = []
                        for i in (1,2,3,0):
                                garr = []
                                a = eval("'"+f.readline().rstrip()+"'")
                                if a.find(',') >= 0:
                                        mast = 0
                                        for y in a.split(','):
                                                mast += 1
                                                for x in y.split():
                                                        name = eval(x)
                                                        card = TCard(name,mast)
                                                        carr.append(card)
                                                        garr.append(card)
                                else:
                                        for x in a.split():
                                                if len(x) > 2:
                                                        name = eval(x[:2])
                                                        mast = eval(x[2])
                                                else:
                                                        name = eval(x[0])
                                                        mast = eval(x[1])
                                                card = TCard(name,mast)
                                                carr.append(card)
                                                garr.append(card)
                                if i:
                                        self.Gamer(i).aCards.Set(garr)
                        coloda.Set(carr)
                        self.nCurrentStart.nValue = eval(f.readline().rstrip())
                        f.close()
                except:
                        pass

        def MkMastTables(self,game=None):
                self.Gamer(1).MakeMastTable(self.Gamer(2),self.Gamer(3),game)
                self.Gamer(2).MakeMastTable(self.Gamer(3),self.Gamer(1),game)
                self.Gamer(3).MakeMastTable(self.Gamer(1),self.Gamer(2),game)
