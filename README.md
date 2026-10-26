# One More Jump

A vertical neon platform jumper with reachability-guaranteed procedural generation and Second Chance checkpoint rewinds.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Pygame](https://img.shields.io/badge/pygame-2.5+-green.svg)](https://www.pygame.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<!-- Gameplay screenshot asset: docs/gameplay.png (to be added) -->

## About

One More Jump is an endless vertical 2D platform jumper for desktop, built with pure Python and Pygame. Inspired by Doodle Jump, the player automatically bounces upon landing on platforms, steering horizontally with real gravity and wrap-around screen edges. All procedural visuals, animations, and sound effects are generated directly in code without any external image or audio asset files.

## Features

- **Responsive movement**: Smooth horizontal steering with seamless screen wrap-around.
- **Guaranteed reachability**: Procedural platform generation governed by analytical physics ceilings, never guesswork.
- **Dynamic platform types**: Standard platforms, dangerous pink spike strips, spring-loaded bounce pads, and fragile crumbling platforms.
- **Risk and reward scoring**: Collect violet bonus orbs and earn "+15 CLOSE!" near-miss points for skimming past spikes.
- **Second Chance rewinds**: Start every run with 3 chances; rewinds restore the player to safe checkpoints or fallback platforms.
- **Midnight Neon aesthetic**: Parallax particle background, glowing shader effects, and player squash-and-stretch animations.
- **Synthesized audio**: Real-time procedural sine-wave audio blips for jumps, boosts, pickups, near misses, rewinds, and game over.
- **Saved high scores**: Automatic local persistence of personal best scores.
- **Complete game loop**: Menus, pause overlay, HUD, and game over screens with both keyboard and mouse support.

## Quick start

### Prerequisites

- Python 3.10 or higher
- Git

### Installation and execution

#### macOS and Linux

```bash
git clone https://github.com/<your-username>/one-more-jump.git
cd one-more-jump
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

#### Windows (PowerShell)

```powershell
git clone https://github.com/<your-username>/one-more-jump.git
cd one-more-jump
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

## Controls

| Screen | Input | Action |
| :--- | :--- | :--- |
| **Playing** | `A` / `D` or `Left` / `Right` Arrow | Steer player horizontally |
| **Playing** | `P` or `ESC` | Pause game |
| **Playing** | Mouse Left Click on top pause button | Pause game |
| **Menu** | `Space` or `Enter` | Start run |
| **Menu** | `ESC` | Quit game |
| **Menu** | Mouse Left Click on **PLAY** | Start run |
| **Paused** | `Space`, `Enter`, `ESC`, or `P` | Resume game |
| **Paused** | Mouse Left Click on buttons | **RESUME**, **RESTART**, or return to **MENU** |
| **Game Over** | `Space` or `Enter` | Play again |
| **Game Over** | `ESC` | Return to menu |
| **Game Over** | Mouse Left Click on buttons | **PLAY AGAIN** or return to **MENU** |

## How to play

The objective is to climb as high as possible. Bouncing is automatic on contact with the top of a platform. Your total score is the sum of climb height (`climb_pixels // 10`) and bonus score gathered from orbs and close calls.

### Legend

| Element | Color | Description |
| :--- | :--- | :--- |
| **Platform** | Cyan (`#22E6D4`) | Standard landing surface; restores upward jump velocity. |
| **Spikes** | Neon Pink (`#FF4182`) | Hazardous platform section; triggers a rewind or game over on contact. |
| **Bounce Pad** | Bright Lime (`#78FF8C`) | Platform spring; launches player to 1.6× standard apex (~320 px). |
| **Crumbler** | Dark Teal (`#1AA0AA`) | Fragile platform; disintegrates 0.35 s after landing. |
| **Bonus Orb** | Violet (`#AA78FF`) | Normal collectible orb; awards +10 bonus points. |
| **Risk Orb** | Large Violet (`#AA78FF`) | High-risk orb hovering above spikes; awards +30 bonus points. |

- **Near-Miss Bonus**: Skimming within 16 px of a spike hitbox without touching it awards "+15 CLOSE!".
- **Second Chance**: You start with 3 chances shown as cyan pips in the HUD. Falling or touching spikes decrements one chance and rewinds you to safety. When 0 chances remain, the next mistake ends the run.

## How it works (technical)

### Architecture

| File | Responsibility |
| :--- | :--- |
| `settings.py` | Centralized constants, derived physics parameters, color definitions. |
| `dsa.py` | Bounded generic LIFO Stack used for checkpoint tracking. |
| `game.py` | State simulation, physics, procedural generation, collisions, scoring. |
| `renderer.py` | Visual rendering, particles, fonts, procedural sound synthesis, UI layout. |
| `main.py` | Application entry point, event dispatch, 60 FPS clock loop. |

The codebase enforces a strict separation of concerns: `renderer.py` reads simulation state without modifying any gameplay rules.

### Physics and collision

- **Gravity & Jump**: Gravity applies a constant downward acceleration of 1800 px/s²; jumps apply an instantaneous upward velocity of -850 px/s.
- **One-Way Platform Landing**: Evaluated only when moving downwards (`vy > 0`). Landing triggers when the player's bottom edge crosses the platform top from above (`prev_bottom <= top <= current_bottom`) with horizontal overlap.
- **Wrap-Around**: Moving across the left or right screen boundary teleports the player to the opposite side.
- **Swept Bounding Boxes**: Fast entity pickups and near-miss checks use swept bounding geometry to prevent tunneling between frames.

### Procedural generation

Reachability is analytically derived from fundamental equations rather than tuned by trial:

$$\text{Jump Height} = \frac{v^2}{2g} \approx 200.7\text{ px} \implies \text{MAX\_GAP\_LIMIT} = 0.75 \times \text{Jump Height} \approx 150.5\text{ px}$$

$$\text{Air Time} = \frac{2|v|}{g} \approx 0.944\text{ s} \implies \text{MAX\_DX} = \text{Air Time} \times \text{Move Speed} \times 0.6 \approx 181.3\text{ px}$$

Vertical gaps, platform widths, and forced horizontal offsets scale smoothly between score 0 and score 1100 (`DIFFICULTY_RAMP_SCORE`), strictly bounded by `MAX_GAP_LIMIT` and `MAX_DX`. Pruning never removes entities at or above the oldest checkpoint or safe platform fallback.

### Data structures

- **Platform Storage**: A standard Python `list` stores active platforms. Because off-screen platforms are culled, the list stays small (~15–25 items), making linear iterations faster and simpler than complex spatial trees.
- **Bounded LIFO Stack (`dsa.py`)**: Stores checkpoint coordinates `(x, y, w, h)` with capacity 3 (`STACK_CAPACITY`). Only plain platforms higher than the previous checkpoint are pushed. When full, pushing discards the oldest element at index 0.
- **Complexity**: `pop()`, `peek()`, `is_empty()`, and `size()` operate in $O(1)$ time. `push()` runs in amortized $O(1)$ time; list deletion on overflow is $O(N)$ where $N \le 3$, which is negligible.
- **Decoupled Chances**: Player chances (`self.chances = 3`) are decoupled from the stack size. If the stack is empty during a rewind, the game falls back to `self.last_safe_platform` (the most recent plain platform landed on), ensuring a rewind never fails while chances remain.

### Second Chance guarantees

- **Score preservation**: Height score, maximum reached height, and bonus score are never reset or reduced by a rewind.
- **Safe landing**: The player is always restored atop an existing, plain platform (never spikes, pads, or crumbling surfaces).
- **Invulnerability**: Grants 1.0 second of invulnerability to prevent immediate repeated hits.
- **Crumbler restoration**: All crumbling platforms are restored to intact upon rewind so the ascent route remains climbable.

## Configuration and tuning

Key constants in `settings.py`:

| Constant | Value | Effect |
| :--- | :--- | :--- |
| `CHANCES_PER_RUN` | `3` | Number of Second Chances granted per run. |
| `GAP_START_MIN` / `GAP_START_MAX` | `100` / `130` | Minimum and maximum platform vertical gap at score 0. |
| `GAP_FINAL_MIN` / `GAP_FINAL_MAX` | `132` / `150.5` | Minimum and maximum platform gap at full difficulty (`GAP_FINAL_MAX` = `MAX_GAP_LIMIT`). |
| `MIN_DX_START` / `MIN_DX_FINAL` | `85` / `150` | Forced horizontal offset between consecutive platforms. |
| `PLATFORM_START_WIDTH` / `PLATFORM_MIN_WIDTH` | `90` / `50` | Starting and fully ramped platform widths. |
| `DIFFICULTY_RAMP_SCORE` | `1100` | Height score where gap, width, and offset scaling saturates. |
| `SPIKE_START_SCORE` / `HAZARD_FULL_SCORE` | `150` / `1500` | Height score where spikes begin and reach peak frequency. |
| `SPIKE_CHANCE_START` / `SPIKE_CHANCE_FINAL` | `0.15` / `0.35` | Spawn probability of spikes on eligible platforms. |
| `PAD_START_SCORE` / `CRUMBLE_START_SCORE` | `100` / `200` | Height score where bounce pads and crumblers start spawning. |
| `ORB_START_SCORE` / `ORB_CHANCE` | `50` / `0.35` | Height score where bonus orbs start spawning and generation chance. |
| `NEAR_MISS_MARGIN` / `NEAR_MISS_POINTS` | `16` / `15` | Proximity margin around spikes (px) and points awarded for near misses. |

## Testing

Run the automated test suite with:

```bash
.venv/bin/python test_game.py
```

The test suite contains 22 comprehensive test suites covering:
- Bounded Stack operations, capacity bounds, and eviction invariants.
- Analytical reachability proofs across 10,000+ generated platforms.
- Collision detection, one-way platform landings, and wrap-around boundaries.
- Score monotonicity, bonus accumulation, and isolated high-score serialization.
- Hazard progression, fairness guarantees, and near-miss bonus mechanics.
- Bounce pad boosts, crumbling platforms, route integrity, and intact crumbler restoration.
- Second Chance rewind sequence, empty-stack fallbacks, and HUD pips.
- A 20,000-frame automated AI stability soak test simulating complete gameplay runs.

**Status**: `ALL TESTS PASSED SUCCESSFULLY!`

## Project structure

```text
one-more-jump/
├── docs/                 # Documentation assets (.gitkeep)
├── .gitignore            # Git exclusions (.venv, caches, highscore.json)
├── dsa.py                # Generic bounded LIFO Stack data structure
├── game.py               # Core game simulation, physics, generation, and rewind
├── highscore.json        # Saved local best score (created at runtime, ignored by git)
├── LICENSE               # MIT open-source license
├── main.py               # Application entry point and event dispatch loop
├── README.md             # Project documentation and developer guide
├── renderer.py           # Pygame rendering, HUD, animations, and sound synth
├── requirements.txt      # Python dependencies (pygame>=2.5)
├── settings.py           # Centralized gameplay constants and derived physics
└── test_game.py          # 22-test automated test suite and headless soak runner
```

## Troubleshooting

-   **`ModuleNotFoundError: No module named 'pygame'`**: The virtual environment is either inactive or missing dependencies. Run `source .venv/bin/activate` (or `.venv\Scripts\Activate.ps1` on Windows) and run `pip install -r requirements.txt`.
- **No audio plays**: `pygame.mixer` could not find an available output device. The game safely catches audio initialization errors and runs in silent mode without crashing.
- **Window fails to open on macOS**: Ensure you are launching with the virtual environment's Python binary (`.venv/bin/python main.py`) to ensure proper framework access for GUI windows.
- **Resetting high score**: Remove the `highscore.json` file in the project root (`rm highscore.json`). A clean file will be re-created upon your next game over.

## Roadmap and ideas

- **Biomes & color themes**: Shift visual themes and parallax starfields every 1,000 vertical meters.
- **Daily seeded runs**: Provide a synchronized daily seed so players can compete on identical platform layouts.
- **Ghost height marker**: Draw a subtle neon line marking your personal best altitude during a run.
- **Particle trails**: Add subtle trailing embers following the player during high-velocity pad launches.

## Credits and license

Inspired by Lima Sky's *Doodle Jump* (independent fan homage, no affiliation).

Distributed under the [MIT License](LICENSE).
