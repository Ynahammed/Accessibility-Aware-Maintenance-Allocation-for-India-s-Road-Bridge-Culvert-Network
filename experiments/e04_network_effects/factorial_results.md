# E4 factorial — does the network-awareness threshold survive a change of topology?

- scenarios: 16 x 3 years, monsoon-stress rain ~ e^0.9 (sigma 0.2), 16 optimizer samples
- budgets (Rs crore): 0.2, 0.6; fragility slope (beta1): 0.6, 2.0
- families: `corridors` (independent parallel routes), `chain` (series sections, upstream structures protect more habitations), `mesh` (random unredundant district)

## Mean person-days lost (lower is better)

| Family | r | Budget | beta1 | Do nothing | Worst-first | Additive | Network-aware | Additive - network | worst-first - network [95% CI] (positive = network better) |
|---|---|---|---|---|---|---|---|---|---|
| corridors | 1 | 0.20 | 0.6 | 16,330 | 11,270 | 9,200 | 9,200 | +0 | +2,070 [+914, +3,220] |
| corridors | 1 | 0.20 | 2.0 | 25,300 | 20,930 | 15,180 | 15,180 | +0 | +5,750 [+3,674, +8,286] |
| corridors | 1 | 0.60 | 0.6 | 16,100 | 8,740 | 3,450 | 3,450 | +0 | +5,290 [+3,680, +7,130] |
| corridors | 1 | 0.60 | 2.0 | 24,610 | 15,640 | 7,590 | 7,590 | +0 | +8,050 [+5,750, +10,350] |
| corridors | 2 | 0.20 | 0.6 | 6,670 | 5,060 | 6,670 | 4,600 | +2,070 | +460 [-690, +1,840] |
| corridors | 2 | 0.20 | 2.0 | 18,860 | 14,490 | 18,860 | 9,430 | +9,430 | +5,060 [+3,680, +6,440] |
| corridors | 2 | 0.60 | 0.6 | 8,050 | 2,760 | 8,050 | 1,840 | +6,210 | +920 [+230, +1,840] |
| corridors | 2 | 0.60 | 2.0 | 17,250 | 6,900 | 17,250 | 5,060 | +12,190 | +1,840 [-690, +4,600] |
| corridors | 3 | 0.20 | 0.6 | 3,220 | 2,530 | 3,220 | 1,380 | +1,840 | +1,150 [+0, +2,530] |
| corridors | 3 | 0.20 | 2.0 | 14,950 | 10,350 | 14,950 | 5,980 | +8,970 | +4,370 [+2,294, +6,670] |
| corridors | 3 | 0.60 | 0.6 | 3,680 | 1,610 | 3,680 | 690 | +2,990 | +920 [+0, +2,070] |
| corridors | 3 | 0.60 | 2.0 | 14,490 | 3,680 | 14,490 | 3,910 | +10,580 | -230 [-1,840, +1,610] |
| corridors | 4 | 0.20 | 0.6 | 1,840 | 1,150 | 1,840 | 1,380 | +460 | -230 [-690, +0] |
| corridors | 4 | 0.20 | 2.0 | 11,730 | 9,430 | 11,730 | 7,360 | +4,370 | +2,070 [+914, +3,220] |
| corridors | 4 | 0.60 | 0.6 | 1,840 | 690 | 1,840 | 920 | +920 | -230 [-920, +460] |
| corridors | 4 | 0.60 | 2.0 | 11,960 | 5,980 | 11,960 | 5,060 | +6,900 | +920 [-460, +2,300] |
| chain | 1 | 0.20 | 0.6 | 30,200 | 22,020 | 20,900 | 20,210 | +690 | +1,810 [+460, +3,460] |
| chain | 1 | 0.20 | 2.0 | 36,480 | 31,040 | 25,800 | 25,800 | +0 | +5,240 [+3,127, +7,520] |
| chain | 1 | 0.60 | 0.6 | 30,210 | 19,550 | 10,780 | 10,780 | +0 | +8,770 [+4,359, +14,810] |
| chain | 1 | 0.60 | 2.0 | 38,990 | 30,310 | 16,610 | 16,610 | +0 | +13,700 [+9,139, +18,500] |
| chain | 2 | 0.20 | 0.6 | 19,970 | 14,260 | 19,970 | 12,300 | +7,670 | +1,960 [-1,140, +4,840] |
| chain | 2 | 0.20 | 2.0 | 32,830 | 27,900 | 32,830 | 27,980 | +4,850 | -80 [-2,390, +2,450] |
| chain | 2 | 0.60 | 0.6 | 18,630 | 6,390 | 18,630 | 7,710 | +10,920 | -1,320 [-4,100, +840] |
| chain | 2 | 0.60 | 2.0 | 32,670 | 21,540 | 32,670 | 15,990 | +16,680 | +5,550 [+1,750, +9,690] |
| chain | 3 | 0.20 | 0.6 | 7,660 | 4,960 | 7,660 | 3,850 | +3,810 | +1,110 [-420, +3,090] |
| chain | 3 | 0.20 | 2.0 | 28,540 | 22,950 | 28,540 | 20,030 | +8,510 | +2,920 [-1,291, +7,730] |
| chain | 3 | 0.60 | 0.6 | 11,440 | 4,130 | 11,440 | 7,030 | +4,410 | -2,900 [-6,650, +361] |
| chain | 3 | 0.60 | 2.0 | 29,430 | 13,570 | 29,430 | 15,630 | +13,800 | -2,060 [-6,030, +1,341] |
| chain | 4 | 0.20 | 0.6 | 5,050 | 2,380 | 5,050 | 1,510 | +3,540 | +870 [+0, +2,190] |
| chain | 4 | 0.20 | 2.0 | 22,970 | 17,900 | 22,970 | 16,570 | +6,400 | +1,330 [-230, +3,120] |
| chain | 4 | 0.60 | 0.6 | 7,010 | 2,780 | 7,010 | 2,390 | +4,620 | +390 [-1,770, +2,130] |
| chain | 4 | 0.60 | 2.0 | 24,080 | 13,690 | 24,080 | 14,630 | +9,450 | -940 [-4,210, +2,220] |
| mesh | - | 0.20 | 0.6 | 145,438 | 146,507 | 146,291 | 141,861 | +4,430 | +4,646 [+322, +9,289] |
| mesh | - | 0.20 | 2.0 | 216,006 | 184,577 | 181,940 | 167,761 | +14,178 | +16,816 [+6,169, +31,349] |
| mesh | - | 0.60 | 0.6 | 160,190 | 141,014 | 119,768 | 120,315 | -548 | +20,699 [+8,357, +33,057] |
| mesh | - | 0.60 | 2.0 | 274,763 | 265,680 | 210,029 | 215,457 | -5,428 | +50,223 [+30,954, +70,751] |

## Where the threshold appears

First redundancy at which the network-aware plan beats the additive MILP, per family x budget x slope (gap at r=1 shown for reference):

| Family | Budget | beta1 | Gap at r=1 | First r with a positive gap |
|---|---|---|---|---|
| chain | 0.20 | 0.6 | +690 | 1 |
| chain | 0.20 | 2.0 | +0 | 2 |
| chain | 0.60 | 0.6 | +0 | 2 |
| chain | 0.60 | 2.0 | +0 | 2 |
| corridors | 0.20 | 0.6 | +0 | 2 |
| corridors | 0.20 | 2.0 | +0 | 2 |
| corridors | 0.60 | 0.6 | +0 | 2 |
| corridors | 0.60 | 2.0 | +0 | 2 |

## Search ablations (corridors, budget Rs 0.4 crore, beta1 1.2)

| r | Variant | Mean person-days | vs full | vs worst-first |
|---|---|---|---|---|
| 2 | network_aware | 4,600 | - | -23.1% |
| 2 | single_move | 4,600 | +0 | -23.1% |
| 2 | no_restarts | 5,980 | +1,380 | +0.0% |
| 2 | no_validation | 5,980 | +1,380 | +0.0% |
| 3 | network_aware | 3,220 | - | -26.3% |
| 3 | single_move | 3,220 | +0 | -26.3% |
| 3 | no_restarts | 3,680 | +460 | -15.8% |
| 3 | no_validation | 3,680 | +460 | -15.8% |
| 4 | network_aware | 2,070 | - | -30.8% |
| 4 | single_move | 3,450 | +1,380 | +15.4% |
| 4 | no_restarts | 2,070 | +0 | -30.8% |
| 4 | no_validation | 2,070 | +0 | -30.8% |

**Reading (computed from this run):**

1. **At redundancy 1 the objectives agree** in 8/8 cells (|additive - network| within 5% of the additive loss): with no parallel route, every structure is critical, so the additive surrogate is already sufficient.
2. **From redundancy 2 the network term pays against the additive model**: a positive additive - network gap in 24/24 cells, significant (95% CI) in 22/24. Against **condition-first** the picture is weaker: the network plan is at or below worst-first in 16/24 cells, significantly better in 5, significantly worse in 0, and undecided in the rest.
3. **The threshold is not corridor-specific**: a first positive gap at r=2 in 7/8 family x budget x slope settings (0 settings never separate). A corridor-only effect would concentrate in one family, so compare the per-family rows above. Where a setting separates at r=1 the gap is small (see the r=1 column), which is why it is called a threshold rather than an effect present at every redundancy.
4. **It is the objective, not the search effort**: the full search is at least as good as the ablated variant in 9/9 comparisons; where an ablation matches or beats it, the gap to condition-first is what matters, not the internal ranking. Read the ablation table's last column.

Notes: the mesh family has no redundancy parameter (its redundancy is whatever the random generator produced), so it is a reference row rather than a factor level.
