#
# PyPref - Preference game for Windows, *NIX and Pocket PC
# This source code is based on kpref by Azarniy I.V.
# and OpenPref (http://openpref.narod.ru)
#
# Author (version 2.0): Alexander aka amigo <amigo12@newmail.ru> - Aug 2007
# Versions 2.1-2.34: Vadim Zapletin <preference.gixx@mail.ru> - Feb-Mar 2018
# License: GNU GPL
#

CARDINCOLODA = 32
MAXMASTLEN = 8

# Game modes
halt = 0
demo = 1
run = 2
stop = 3

# Options
wait = 0
hintcard = 1
hintgame = 2
hintdiscard = 3
lang = 4
corder = 5
sorder = 6
selkey = 7
lighton = 8
leftlvl = 9
rightlvl = 10
greedywhist = 11
pasprogress = 12
pasexit = 13
pastalon = 14
scorerules = 15
without3 = 16
check10 = 17
responsible = 18
halfwhist = 19
whistpas = 20
stalingrad = 21
lostexit = 22

# TSide
left = 0
right = 1
noside = 2

# TMast
pica = 1
trefa = 2
bubna = 3
cherva = 4
withoutmast = 5

# TGamesType
zerogame = 0
bez3 = 54
halfvist = 55
g86catch = 56
raspas = 57
vist = 58
undefined = 59
pas = 60
g61 = 61
g62 = 62
g63 = 63
g64 = 64
g65 = 65
g71 = 71
g72 = 72
g73 = 73
g74 = 74
g75 = 75
g81 = 81
g82 = 82
g83 = 83
g84 = 84
g85 = 85
g86 = 86
g91 = 91
g92 = 92
g93 = 93
g94 = 94
g95 = 95
g101 = 101
g102 = 102
g103 = 103
g104 = 104
g105 = 105

GamesList = [
g86,
pas,
g61,
g62,
g63,
g64,
g65,
g71,
g72,
g73,
g74,
g75,
g81,
g82,
g83,
g84,
g85,
g91,
g92,
g93,
g94,
g95,
g101,
g102,
g103,
g104,
g105,
]

# Game rules
Sochi = 0
Peter = 1
Rostov = 2

## some externs
#g61stalingrad = None
#g10vist = None
#globvist = True
##nBulletScore = -1
##CurrentGame = None
##nRaspasCnt = 0
#gui = None

# some structs
class TMastTable:
        def __init__(self):
                self.reset()            
        def reset(self):
                self.vzatok = 0
                self.perehvatov = 0
                self.len = 0
                self.sum = 0
                self.max = None
                self.min = None
                self.othodov = 0
                self.vz23 = 0
                self.min23 = 0
                self.elen = 0

def NextGame(game):
        if game == g86:
                return g91
        if game == undefined:
                return g61
        if game == g105:
                return game
        try:
                i = GamesList.index(game)
                return GamesList[i+1]
        except:
                return pas

def sGameName(game):
        if game == vist:
                return 'vist'
        if game == pas:
                return 'pass'
        if game == g86:
                return 'miser'
        if game == g86catch:
                return ''
        return str(game)

def nGetGameCard(game):
        if game == g86:
                return 0
        if game < g61:
                return 6
        return int(game/10)

def nGetVistCard(game):
        if game >= g71 and game <= g75:
                return 2
        if game == g86 or game >= g101 and check10 == 1:
                return 0
        #if game >= g81 and game <= g85 or game >= g91 and game <= g95 or game >= g101 and game <= g105:
        if game >= g81 and game <= g95 or game >= g101 and not check10 == 1:
                return 1
        return 4

def nGetMinCard4Vist(game):
        if game >= g71 and game <= g75:
                return 2
        if game == g86 or game >= g101 and check10 == 1:
                return 0
        if game >= g81 and game <= g85 or game >= g91 and game <= g95 or game >= g101 and not check10 == 1:
                return 1
        return 4

def nGetGamePrice(game):
        if game >= g71 and game <= g75:
                return 4
        if game == g86 or game >= g101 and game <= g105:
                return 10
        if game >= g81 and game <= g85:
                return 6
        if game >= g91 and game <= g95:
                return 8
        if game == raspas:
                return 1
        return 2

def GamesTypeByName(name):
        try:
                return eval(name)
        except:
                None
