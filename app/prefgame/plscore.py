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

from prefgame.prfconst import *
from prefgame.ctlist import *

class TPlScore:
        glob = 0
        resp = 0
        rule = 0
        rcnt = 0
        rprg = 0
        lost = 0

        def __init__(self):
                self.Bullet = Tclist()
                self.Mountan = Tclist()
                self.LeftVists = Tclist()
                self.RightVists = Tclist()
                self.New = [0,0,0,0]
                self.Vists = 0
                self.nBuletScore = 21

        def Setup(self,opt):
                TPlScore.glob = opt[greedywhist]
                TPlScore.resp = opt[responsible]
                TPlScore.rule = opt[scorerules]
                TPlScore.rprg = opt[pasprogress]
                TPlScore.lost = opt[lostexit]
                TPlScore.prov = opt[check10]

        def AddBullet(self,val):
                #print 'AddBull', val
                nScore = self.nGetBull()
                if nScore+val <= self.nBulletScore or TPlScore.rule == Peter:
                        self.Bullet.Insert(nScore+val)
                        self.New[0] = 1
                        return 0
                else:
                        if self.nBulletScore != self.nGetBull():
                                self.Bullet.Insert(self.nBulletScore)
                                self.New[0] = 1
                        return val - (self.nBulletScore-nScore)

        def MountanDown(self,val):
                #print 'MountDown', val
                nScore = self.nGetMount() - val
                if nScore >= 0:
                        self.Mountan.Insert(nScore)
                        self.New[1] = 1
                else:
                        nScore = (val-self.nGetMount())*10//3
                        if self.nGetMount():
                                self.Mountan.Insert(0)
                                self.New[1] = 1
                        self.LeftVists.Insert(self.nGetLeftVists()+nScore)
                        self.RightVists.Insert(self.nGetRightVists()+nScore)
                        self.New[2] = self.New[3] = 1

        def MountanUp(self,val):
                #print 'MountUp', val
                nScore = self.nGetMount()
                self.Mountan.Insert(nScore+val)
                self.New[1] = 1

        def AddVist(self,index,myNumber,Skolko):
                #print 'AddVist', index, myNumber, Skolko
                if myNumber == 1 and index == 2 or myNumber == 2 and index == 3 or myNumber == 3 and index == 1:
                        NaKogo = self.LeftVists
                        nidx = 2
                else:
                        NaKogo = self.RightVists
                        nidx = 3
                pnCurrent = NaKogo.LastItem()
                nScore = Skolko*10 + (pnCurrent or 0)
                NaKogo.Insert(nScore)
                self.New[nidx] = 1

        def AddRecords(self,aGamerType,aMyType,nGamerVz,nMyVz,nGamer,myNumber,nqVist,dt):
                #pdb.set_trace()
                #print 'AddRec', aGamerType,aMyType,nGamerVz,nMyVz,nGamer,myNumber,nqVist
                if aGamerType == bez3:
                        if aMyType >= g61:
                                nGamePrice = nGetGamePrice(aMyType)
                                nScore = nGamePrice * 3
                                self.MountanUp(nScore)
                        return 0

                rule = TPlScore.rule
                globvist = TPlScore.glob
                proverka10 = TPlScore.prov
                #print "### GLOB",globvist
                nGamePrice = nGetGamePrice(aGamerType)
                nGameCard = nGetGameCard(aGamerType)
                nVistCard = nGetVistCard(aGamerType)
                #print 'GP', nGamePrice, 'GC', nGameCard, 'VC', nVistCard
                nScore = 0
                pnCurrent = None

                if aMyType >= g61 and aMyType != g86:
                        if nGamerVz >= nGameCard:
                                TPlScore.rcnt = 0
                                return self.AddBullet(nGamePrice)
                        else:
                                if TPlScore.lost:
                                        TPlScore.rcnt = 0
                                #pnCurrent = self.Mountan.LastItem()
                                #nScore = nGamePrice * (nGameCard-nMyVz) + (pnCurrent or 0)
                                if rule == Peter:
                                        nScore = nGamePrice * 2 * (nGameCard-nMyVz)
                                else:
                                        nScore = nGamePrice * (nGameCard-nMyVz)
                                if nScore:
                                        #self.Mountan.Insert(nScore)
                                        self.MountanUp(nScore)
                        return 0

                if aMyType == g86:
                        if nMyVz:
                                if TPlScore.lost:
                                        TPlScore.rcnt = 0
                                if rule == Peter:       
                                        self.MountanUp(nGamePrice*2*nMyVz)
                                else:
                                        self.MountanUp(nGamePrice*nMyVz)
                                return 0
                        TPlScore.rcnt = 0
                        return self.AddBullet(nGamePrice)

                if aMyType == raspas:
                        if myNumber == 1:
                                TPlScore.rcnt += 1
                        cnt = TPlScore.rcnt
                        prg = TPlScore.rprg
                        if cnt > 1:
                                if prg == 0:
                                        cnt = 1
                                elif prg == 1 and cnt > 3:
                                        cnt = 3
                                elif prg > 2:
                                        cnt = pow(2,(cnt-1))
                                        if prg == 3 and cnt > 4:
                                                cnt = 4
                        #print "### RASPAS",TPlScore.rcnt,cnt
                        if rule == Peter:
                                nGamePrice *= 2
                        elif rule == Rostov:
                                nGamePrice = 5
                        nGamePrice *= cnt
                        if rule == Rostov:
                                (left,right) = self.LeftRight(myNumber,dt)
                                if nMyVz < left.nGetsCard and nMyVz < right.nGetsCard:
                                        self.LeftVists.Insert(nGamePrice*left.nGetsCard + (self.LeftVists.LastItem() or 0))
                                        self.RightVists.Insert(nGamePrice*right.nGetsCard + (self.RightVists.LastItem() or 0))
                                        self.New[2] = self.New[3] = 1
                                elif nMyVz < left.nGetsCard and nMyVz == right.nGetsCard:
                                        self.LeftVists.Insert(nGamePrice*left.nGetsCard//2 + (self.LeftVists.LastItem() or 0))
                                        self.New[2] = 1
                                elif nMyVz == left.nGetsCard and nMyVz < right.nGetsCard:
                                        self.RightVists.Insert(nGamePrice*right.nGetsCard//2 + (self.RightVists.LastItem() or 0))
                                        self.New[3] = 1
                                if nMyVz:
                                        return 0
                                return self.AddBullet(cnt)
                        else:
                                nScore = nGamePrice * nMyVz
                                if nScore:
                                        #self.Mountan.Insert(nScore)
                                        self.MountanUp(nScore)
                                        return 0
                                return self.AddBullet(nGamePrice)

                if myNumber == 1 and nGamer == 2 or myNumber == 2 and nGamer == 3 or myNumber == 3 and nGamer == 1:
                        NaKogo = self.LeftVists
                        nidx = 2
                else:
                        NaKogo = self.RightVists
                        nidx = 3
                pnCurrent = NaKogo.LastItem()

                if aMyType == pas and aGamerType != g86 and dt.Gamer(myNumber).MaxGame != halfvist:
                        if rule == Peter:
                                nGamePrice *= 2
                        Remiz = (rule == Rostov and 10 or nGamePrice)
                        if nGameCard-nGamerVz > 0:
                                if globvist:
                                        #nScore = nGamePrice*(nGameCard-nGamerVz)
                                        nScore = Remiz*(nGameCard-nGamerVz)
                                else:
                                        #nScore = nGamePrice*(nGameCard-nGamerVz)+(10-nGamerVz)*nGamePrice/2
                                        nScore = (Remiz*2*(nGameCard-nGamerVz)+(10-nGamerVz)*nGamePrice)//2
                        if nScore:
                                NaKogo.Insert(nScore + (pnCurrent or 0))
                                self.New[nidx] = 1

                if (aMyType == vist or aMyType == halfvist) and aGamerType != g86:
                        if rule == Peter:
                                nGamePrice *= 2
                        Remiz = (rule == Rostov and 10 or nGamePrice)
                        if nGameCard-nGamerVz > 0:
                                if nqVist == 2:                                        
                                        #nScore = nGamePrice*((nGameCard-nGamerVz)+nMyVz)
                                        nScore = Remiz*(nGameCard-nGamerVz)+nGamePrice*nMyVz
                                else:
                                        (left,right) = self.LeftRight(myNumber,dt)
                                        if left.MaxGame == halfvist or right.MaxGame == halfvist:
                                                nScore = Remiz*2*(nGameCard-nGamerVz)+nGamePrice*(10-nGamerVz)
                                        elif globvist:
                                                #nScore = nGamePrice*((nGameCard-nGamerVz)+(10-nGamerVz))
                                                nScore = Remiz*(nGameCard-nGamerVz)+nGamePrice*(10-nGamerVz)
                                        else:
                                                #nScore = nGamePrice*(nGameCard-nGamerVz)+(10-nGamerVz)*nGamePrice/2
                                                nScore = (Remiz*2*(nGameCard-nGamerVz)+(10-nGamerVz)*nGamePrice)//2
                        else:
                                if nqVist == 2:
                                        nScore = nGamePrice*nMyVz
                                elif aMyType == halfvist:
                                        nScore = nGamePrice*int(nMyVz/2)
                                else:
                                        nScore = nGamePrice*(10-nGamerVz)
                                if nVistCard > (10-nGamerVz) and not proverka10:
                                        if nqVist == 2:
                                                if aGamerType >= g81:
                                                        # Second whist responsible
                                                        (left,right) = self.LeftRight(myNumber,dt)
                                                        if right.nGamer == nGamer:
                                                                mScore = 0
                                                        else:
                                                                mScore = nGamePrice
                                                #else:
                                                        #mScore = int(float(nVistCard)/2 - nMyVz) * nGamePrice
                                                elif nMyVz < nVistCard//2:
                                                        # Za nedobor - rx56
                                                        mScore = (nVistCard//2-nMyVz) * nGamePrice
                                                else:
                                                        mScore = 0
                                        #elif nVistCard - nMyVz > 0:
                                        else:
                                                mScore = (nVistCard - (10-nGamerVz)) * nGamePrice                                                
                                        if mScore > 0:
                                                if not TPlScore.resp:
                                                        mScore /= 2
                                                self.MountanUp(mScore)
                        if nScore:
                                NaKogo.Insert(nScore + (pnCurrent or 0))
                                self.New[nidx] = 1

                return 0

        def nGetBull(self):
                return (self.Bullet.LastItem() or 0)

        def nGetMount(self):
                return (self.Mountan.LastItem() or 0)

        def nGetLeftVists(self):
                return (self.LeftVists.LastItem() or 0)

        def nGetRightVists(self):
                return (self.RightVists.LastItem() or 0)

        def LeftRight(self,myNumber,dt):
                if myNumber == 1:
                        return (dt.Gamer(2),dt.Gamer(3))
                if myNumber == 2:
                        return (dt.Gamer(3),dt.Gamer(1))
                return (dt.Gamer(1),dt.Gamer(2))
