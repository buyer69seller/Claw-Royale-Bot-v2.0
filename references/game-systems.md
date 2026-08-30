# Game Systems - Claw Royale

## Map System
- Size: 20x20 grid
- Visibility: 5 tile radius

### Terrain Types
| Terrain | Effect |
|---------|--------|
| Grass | None |
| Forest | +1 DEF |
| Water | -1 Move |
| Mountain | +2 DEF |
| Cave | Hidden |
| Ruin | Explore |

## Guardian System
- Spawn at random ruins
- Guard relics and packs
- Attack players who enter ruins

## Alert System
- Alert gauge: 0-10
- Each explore: +2 alert
- At 10: `alertActive: true`

## Ruin System
- 5 ruins per map
- 3 exploration charges per ruin
- Rewards: Pack or Relic