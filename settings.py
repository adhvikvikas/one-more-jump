"""Game settings and constants for One More Jump.

All constants are centralized here. Derived values for reachability and
jump physics are computed analytically from fundamental equations.
"""

import math
from pathlib import Path

# --- Window & Timing ---
WIDTH = 480
HEIGHT = 720
FPS = 60
TITLE = "One More Jump"

# --- Colors (Midnight Neon Theme) ---
BG_COLOR = (11, 16, 38)            # Deep midnight navy
GRID_COLOR = (20, 28, 60)          # Subtle background grid lines
PARTICLE_COLOR = (32, 45, 90)      # Drifting background parallax stars/dots
PLATFORM_COLOR = (34, 230, 212)    # Radiant turquoise / cyan
PLATFORM_TOP_COLOR = (180, 255, 250) # Highlight on platform top surface
PLATFORM_GLOW_COLOR = (18, 110, 105) # Subtle glow backdrop behind platform
PLAYER_COLOR = (255, 235, 120)     # Warm glowing yellow/amber player
PLAYER_EYE_COLOR = (15, 20, 45)    # Player eye pupil color
TEXT_COLOR = (245, 248, 255)       # Crisp off-white text
TEXT_MUTED = (140, 155, 195)       # Dim secondary text
ACCENT_COLOR = (255, 65, 130)      # Neon pink / magenta accent for badges/highlights
BUTTON_BG = (22, 32, 68)           # Unhovered button background
BUTTON_HOVER_BG = (42, 60, 120)    # Hovered button background
BUTTON_BORDER = (50, 200, 210)     # Button neon border
BUTTON_HOVER_BORDER = (255, 100, 160) # Button neon hover border
OVERLAY_COLOR = (11, 16, 38)       # Translucent overlay RGB (alpha blended in code)
FLASH_COLOR = (34, 230, 212)       # Cyan flash on checkpoint rewind
HAZARD_COLOR = ACCENT_COLOR        # Radiant neon pink for hazards and spikes
HAZARD_GLOW_COLOR = (120, 25, 70)  # Darker magenta glow for hazard backdrop

# --- Special Platform Colors (Bounce Pads & Crumblers) ---
PAD_COLOR = (120, 255, 140)        # Bright lime spring coil and cap
PAD_GLOW_COLOR = (30, 110, 60)     # Emerald glow backdrop behind spring
PAD_TOP_COLOR = (200, 255, 210)    # Soft mint highlight on spring cap
CRUMBLE_COLOR = (26, 160, 170)     # Weathered darker teal for fragile platforms
CRUMBLE_TOP_COLOR = (120, 200, 205) # Muted rim highlight for crumbling platform
CRUMBLE_CRACK_COLOR = BG_COLOR     # Deep fissure crack lines matching navy void

# --- Physics Constants ---
GRAVITY = 1800.0                   # px/s^2 downwards
JUMP_VELOCITY = -850.0             # px/s upwards
MOVE_SPEED = 320.0                 # px/s horizontal steering
MAX_FALL_SPEED = 1400.0            # px/s terminal velocity cap

# --- Derived Reachability Physics ---
# Reachability is derived directly from physics equations, not tuned by feel:
# 1. Theoretical jump apex height h = v^2 / (2 * g) (~200.69 px).
#    A 75% safety factor guarantees platforms are easily reachable even with reaction lag.
JUMP_HEIGHT = (JUMP_VELOCITY ** 2) / (2.0 * GRAVITY)
MAX_GAP_LIMIT = 0.75 * JUMP_HEIGHT

# 2. Maximum horizontal span across a full jump trajectory:
#    Total air time from takeoff back to takeoff height = 2 * |v| / g (~0.944 s).
#    Scaled by 0.6 safety factor to ensure players can steer across the gap reliably.
AIR_TIME = (2.0 * abs(JUMP_VELOCITY)) / GRAVITY
MAX_DX = AIR_TIME * MOVE_SPEED * 0.6  # ~181.3 px

# --- Player Properties ---
PLAYER_SIZE = 34
START_X = WIDTH // 2 - PLAYER_SIZE // 2
START_Y = HEIGHT - 140

# --- Platform Properties & Difficulty Scaling (tuned: slightly harder) ---
# Note: Platform dimensions, gaps, and horizontal offsets are starting values meant
# to be tuned by feel; reachability guarantees remain strictly governed by physics-
# derived ceilings MAX_GAP_LIMIT (~150.5 px) and MAX_DX (~181.3 px).
PLATFORM_HEIGHT = 12
PLATFORM_START_WIDTH = 90          # (tuned: slightly harder)
PLATFORM_MIN_WIDTH = 50            # (tuned: slightly harder)
GAP_START_MIN = 100                # (tuned: slightly harder)
GAP_START_MAX = 130                # (tuned: slightly harder)
GAP_FINAL_MIN = 132                # (tuned: slightly harder)
GAP_FINAL_MAX = MAX_GAP_LIMIT      # Strictly capped at MAX_GAP_LIMIT (~150.5 px)

# Forced minimum horizontal offsets between consecutive platforms (ramps with score).
# MIN_DX_FINAL (150 px) must stay well below MAX_DX (~181.3 px) so the reachability
# guarantee still holds even at peak difficulty.
MIN_DX_START = 85                  # (tuned: slightly harder)
MIN_DX_FINAL = 150                 # (tuned: slightly harder)

DIFFICULTY_RAMP_SCORE = 1100       # Score at which difficulty fully saturates (~11,000 px climbing) (tuned: slightly harder)

# --- Camera & Culling ---
CAMERA_THRESHOLD_RATIO = 0.4       # 40% of screen height
PRUNE_MARGIN = 200                 # px below screen bottom before platform is pruned

# --- Checkpoint & DSA Rewind ---
CHANCES_PER_RUN = 3                # Total rewinds / second chances granted per run
STACK_CAPACITY = 3                 # Max checkpoints stored
REWIND_SCREEN_RATIO = 0.7          # Platform placed at 70% of screen height upon rewind
REWIND_FLASH_DURATION = 0.25       # Seconds for rewind screen flash
SQUASH_DURATION = 0.12             # Seconds for landing squash animation

# --- Scoring ---
SCORE_DIVISOR = 10                 # Pixels climbed per score unit

# --- Hazard & Obstacle Settings ---
SPIKE_START_SCORE = 150            # Score at which spiked platforms begin appearing
HAZARD_FULL_SCORE = 1500           # Score at which hazard chances and difficulty saturate
SPIKE_CHANCE_START = 0.15          # Probability of spike hazard on eligible platform at start
SPIKE_CHANCE_FINAL = 0.35          # Probability of spike hazard at full difficulty
HAZARD_CLEAN_GAP_START = 3         # Minimum clean platforms between hazards at start
HAZARD_CLEAN_GAP_FINAL = 1         # Minimum clean platforms between hazards at full difficulty
SPIKE_PLATFORM_MIN_WIDTH = 90      # Minimum platform width when spikes are placed (safe zone guarantee)
SPIKE_COVERAGE = 0.35              # Fraction of platform width covered by spikes
SPIKE_HEIGHT = 14                  # Visual vertical height of spike triangles
SPIKE_HITBOX_SCALE = 0.6           # Fair hitbox scaling (60% width and height, anchored bottom center)
PLAYER_HITBOX_INSET = 6            # Inset from player logical rect edges for fair collision
REWIND_INVULN_DURATION = 1.0       # Seconds of invulnerability granted after rewind

# --- Bonus Orbs & Near-Miss Bonus Settings ---
ORB_START_SCORE = 50               # Score at which bonus orbs begin generating
ORB_CHANCE = 0.35                  # Probability of normal orb in eligible gap
ORB_RADIUS = 11                    # Visual radius of normal bonus orb
ORB_POINTS = 10                    # Points awarded for collecting a normal orb
ORB_CLEARANCE = 6                  # Minimum clearance from platforms, pads, and spikes
ORB_PICKUP_FORGIVENESS = 8         # Extra collision margin for collecting orbs
RISK_ORB_CHANCE = 0.5              # Probability of high-risk orb above spike strip
RISK_ORB_RADIUS = 14               # Visual radius of risk orb
RISK_ORB_POINTS = 30               # Points awarded for collecting a risk orb
RISK_ORB_HEIGHT = 50               # Height offset above spike strip for risk orb
NEAR_MISS_MARGIN = 16              # Extra distance around spike hitbox for close call zone
NEAR_MISS_POINTS = 15              # Points awarded for cleanly skimming past spikes
MAX_FX_PARTICLES = 60              # Cap on active burst particles in renderer
MAX_POPUPS = 8                     # Cap on active floating text popups in renderer
POPUP_DURATION = 0.8               # Seconds floating score popup persists
NEAR_MISS_POPUP_DURATION = 1.0     # Seconds near-miss popup persists
BONUS_PULSE_DURATION = 0.25        # Seconds HUD bonus score flashes on pickup

# --- Bonus Orb & Feedback Colors ---
ORB_COLOR = (170, 120, 255)        # Vibrant violet orb body
ORB_GLOW_COLOR = (70, 40, 130)     # Deep purple glow backdrop
ORB_CORE_COLOR = (240, 225, 255)   # Bright white-lavender core
POPUP_CLOSE_COLOR = PLAYER_COLOR   # Warm amber/yellow for CLOSE! popup

# --- Bounce Pad & Crumbler Platform Features ---
PAD_HEIGHT_FACTOR = 1.6            # Apex height multiplier compared to standard jump (~320 px apex)
PAD_JUMP_VELOCITY = JUMP_VELOCITY * math.sqrt(PAD_HEIGHT_FACTOR) # Boost launch velocity
PAD_WIDTH = 26                     # Visual and physical width of bounce pad spring
PAD_HEIGHT = 10                    # Visual uncompressed height of bounce pad spring
PAD_FORGIVENESS = 6                # Horizontal landing padding (px) each side for triggering pad
PAD_START_SCORE = 100              # Score at which bounce pads begin generating
PAD_CHANCE_START = 0.10            # Spawn probability of bounce pad at start score
PAD_CHANCE_FINAL = 0.14            # Spawn probability of bounce pad at full difficulty
PAD_CLEAR_PLATFORMS = 2            # Clean hazard-free platforms required right after a bounce pad
PAD_PRESS_DURATION = 0.15          # Duration (seconds) of spring compression visual effect

CRUMBLE_START_SCORE = 200          # Score at which crumbling platforms begin generating
CRUMBLE_CHANCE_START = 0.10        # Spawn probability of crumbling platform at start score
CRUMBLE_CHANCE_FINAL = 0.30        # Spawn probability of crumbling platform at full difficulty
CRUMBLE_DELAY = 0.35               # Seconds before platform disintegrates after player contact
CRUMBLE_MIN_PLAIN_BETWEEN = 1      # Minimum non-crumbling platforms between crumbling platforms
MAX_SPECIAL_RUN = 3                # Maximum consecutive non-plain platforms before forcing plain
DEBRIS_DURATION = 0.5              # Seconds falling debris persists before being removed

# --- Persistence ---
HIGHSCORE_PATH = Path(__file__).resolve().parent / "highscore.json"
