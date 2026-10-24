"""Core game logic and physics for One More Jump.

Contains game state, player physics, reachability-constrained procedural
platform generation, collision detection, scoring, and the LIFO checkpoint stack.
No rendering or audio playback code is included here.
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
from typing import List, Optional, Tuple
import pygame

from dsa import Stack
from settings import (
    CAMERA_THRESHOLD_RATIO,
    CHANCES_PER_RUN,
    CRUMBLE_CHANCE_FINAL,
    CRUMBLE_CHANCE_START,
    CRUMBLE_DELAY,
    CRUMBLE_MIN_PLAIN_BETWEEN,
    CRUMBLE_START_SCORE,
    DEBRIS_DURATION,
    DIFFICULTY_RAMP_SCORE,
    GAP_FINAL_MAX,
    GAP_FINAL_MIN,
    GAP_START_MAX,
    GAP_START_MIN,
    GRAVITY,
    HAZARD_CLEAN_GAP_FINAL,
    HAZARD_CLEAN_GAP_START,
    HAZARD_FULL_SCORE,
    HEIGHT,
    HIGHSCORE_PATH,
    JUMP_VELOCITY,
    MAX_DX,
    MAX_FALL_SPEED,
    MAX_GAP_LIMIT,
    MAX_SPECIAL_RUN,
    MIN_DX_FINAL,
    MIN_DX_START,
    MOVE_SPEED,
    NEAR_MISS_MARGIN,
    NEAR_MISS_POINTS,
    ORB_CHANCE,
    ORB_CLEARANCE,
    ORB_PICKUP_FORGIVENESS,
    ORB_POINTS,
    ORB_RADIUS,
    ORB_START_SCORE,
    PAD_CHANCE_FINAL,
    PAD_CHANCE_START,
    PAD_CLEAR_PLATFORMS,
    PAD_FORGIVENESS,
    PAD_HEIGHT,
    PAD_JUMP_VELOCITY,
    PAD_PRESS_DURATION,
    PAD_START_SCORE,
    PAD_WIDTH,
    PLATFORM_HEIGHT,
    PLATFORM_MIN_WIDTH,
    PLATFORM_START_WIDTH,
    PLAYER_HITBOX_INSET,
    PLAYER_SIZE,
    PRUNE_MARGIN,
    REWIND_FLASH_DURATION,
    REWIND_INVULN_DURATION,
    REWIND_SCREEN_RATIO,
    RISK_ORB_CHANCE,
    RISK_ORB_HEIGHT,
    RISK_ORB_POINTS,
    RISK_ORB_RADIUS,
    SCORE_DIVISOR,
    SPIKE_CHANCE_FINAL,
    SPIKE_CHANCE_START,
    SPIKE_COVERAGE,
    SPIKE_HEIGHT,
    SPIKE_HITBOX_SCALE,
    SPIKE_PLATFORM_MIN_WIDTH,
    SPIKE_START_SCORE,
    SQUASH_DURATION,
    STACK_CAPACITY,
    START_X,
    START_Y,
    WIDTH,
)

# Platforms are represented as pygame.Rect instances for geometry and collision
Platform = pygame.Rect


@dataclass
class Hazard:
    """Represents a stationary platform spike strip obstacle."""
    platform: Platform
    rect: pygame.Rect  # Strip rect in world coordinates for spikes
    in_zone: bool = False
    near_miss_awarded: bool = False

    def hitbox(self) -> pygame.Rect:
        """Return the active collision hitbox scaled down for player fairness."""
        # Scaled to 60 percent of width and height, anchored at bottom center
        scaled_w = max(1, int(self.rect.width * SPIKE_HITBOX_SCALE))
        scaled_h = max(1, int(self.rect.height * SPIKE_HITBOX_SCALE))
        center_x = self.rect.centerx
        bottom = self.rect.bottom
        return pygame.Rect(center_x - scaled_w // 2, bottom - scaled_h, scaled_w, scaled_h)


@dataclass
class Orb:
    """Collectible bonus orb offering score points."""
    x: float
    y: float
    radius: float
    points: int
    risk: bool


@dataclass
class Pad:
    """A bounce spring attached to a platform top that boosts jump apex."""
    platform: Platform
    rect: pygame.Rect
    pressed_timer: float = 0.0


@dataclass
class Crumbler:
    """A fragile platform that cracks and disintegrates after player contact."""
    platform: Platform
    state: str = "intact"  # "intact", "crumbling", "broken"
    timer: float = 0.0


@dataclass
class Debris:
    """Falling fragments from a disintegrated crumbling platform."""
    rect: pygame.Rect
    age: float = 0.0


def load_highscore(path: Path = HIGHSCORE_PATH) -> int:
    """Load high score from disk. Silently returns 0 on missing/corrupt data."""
    try:
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    val = data.get("highscore", 0)
                    if isinstance(val, int) and not isinstance(val, bool):
                        return max(0, val)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return 0


def save_highscore(score: int, path: Path = HIGHSCORE_PATH) -> None:
    """Persist high score to disk wrapped in exception handling."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"highscore": int(score)}, f)
    except (OSError, ValueError):
        pass


class Game:
    """Encapsulates all gameplay state, simulation physics, and rule logic."""

    def __init__(self) -> None:
        self.state: str = "menu"  # "menu", "playing", "paused", "game_over"
        self.best_score: int = load_highscore()
        self.score: int = 0
        self.bonus_score: int = 0
        self.max_height_y: float = 0.0
        self.start_y: float = float(START_Y)
        self.camera_y: float = 0.0

        # Player entity physics
        self.player_x: float = float(START_X)
        self.player_y: float = float(START_Y)
        self.player_vx: float = 0.0
        self.player_vy: float = 0.0
        self.player_width: int = PLAYER_SIZE
        self.player_height: int = PLAYER_SIZE

        # Visual feedback timers and sound trigger flags
        self.squash_timer: float = 0.0
        self.rewind_flash_timer: float = 0.0
        self.just_jumped: bool = False
        self.just_boosted: bool = False
        self.just_game_over: bool = False

        # Hazards and obstacles state (stationary spike strips)
        self.hazards: List[Hazard] = []
        self.invuln_timer: float = 0.0
        self.platforms_since_hazard: int = 0
        self.hazards_enabled: bool = True

        # Specials state (bounce pads, crumblers, debris)
        self.pads: List[Pad] = []
        self.crumblers: List[Crumbler] = []
        self.debris: List[Debris] = []
        self.platforms_since_pad: int = 999
        self.platforms_since_crumbler: int = 999
        self.consecutive_special_run: int = 0
        self.specials_enabled: bool = True

        # Collectible bonus orbs and event queue
        self.orbs: List[Orb] = []
        self.events: List[tuple] = []
        self.orbs_enabled: bool = True
        self.last_landing_platform: Optional[Platform] = None

        # Chosen as a simple container; linear scan is fine for a few dozen platforms.
        self.platforms: List[Platform] = []

        # =========================================================================
        # Checkpoint System (DSA Demonstration: LIFO Stack)
        # The checkpoint stack operates on Last-In, First-Out (LIFO) semantics:
        # The most recently saved platform is the first one restored upon a fall.
        # Checkpoints store only platform rect coordinates (x, y, w, h).
        # Capacity is bounded to STACK_CAPACITY; older checkpoints are discarded.
        # =========================================================================
        self.checkpoint_stack: Stack[Tuple[int, int, int, int]] = Stack(STACK_CAPACITY)
        self.last_checkpoint_top_y: float = float("inf")
        self.last_safe_platform: Optional[Platform] = None
        self.chances: int = CHANCES_PER_RUN
        self.run_id: int = 0

    @property
    def total_score(self) -> int:
        """Headline total score combining climb height and collected bonus points."""
        return self.score + self.bonus_score

    def _platform_has_spikes(self, platform: Platform) -> bool:
        """Check whether a given platform carries a spike hazard."""
        for h in self.hazards:
            if h.platform == platform:
                return True
        return False

    def _platform_has_pad(self, platform: Platform) -> Optional[Pad]:
        """Return the bounce pad on this platform if one exists."""
        for pad in self.pads:
            if pad.platform == platform:
                return pad
        return None

    def _get_crumbler(self, platform: Platform) -> Optional[Crumbler]:
        """Return the crumbler record for this platform if one exists."""
        for c in self.crumblers:
            if c.platform is platform:
                return c
        return None

    def _is_plain(self, platform: Platform) -> bool:
        """Check whether platform is plain (no spikes, no bounce pad, not a crumbler)."""
        if self._platform_has_spikes(platform):
            return False
        if any(pad.platform == platform for pad in self.pads):
            return False
        if any(c.platform is platform for c in self.crumblers):
            return False
        return True

    def _circle_overlaps_rect(self, cx: float, cy: float, r: float, rect: pygame.Rect) -> bool:
        """Check whether a circle overlaps a rectangular region."""
        closest_x = max(rect.left, min(rect.right, cx))
        closest_y = max(rect.top, min(rect.bottom, cy))
        return math.hypot(cx - closest_x, cy - closest_y) < r

    def _orb_is_clear(self, cx: float, cy: float, r: float) -> bool:
        """Verify an orb does not overlap any platform, pad, or spike strip with clearance."""
        for p in self.platforms:
            if self._circle_overlaps_rect(cx, cy, r, p.inflate(2 * ORB_CLEARANCE, 2 * ORB_CLEARANCE)):
                return False
        for pad in self.pads:
            if self._circle_overlaps_rect(cx, cy, r, pad.rect.inflate(2 * ORB_CLEARANCE, 2 * ORB_CLEARANCE)):
                return False
        for h in self.hazards:
            if self._circle_overlaps_rect(cx, cy, r, h.rect.inflate(2 * ORB_CLEARANCE, 2 * ORB_CLEARANCE)):
                return False
        return True

    def _make_start_platform(self) -> Platform:
        """Construct the initial safe platform positioned directly under the player."""
        start_plat_width = 140
        start_plat_x = (WIDTH - start_plat_width) // 2
        start_plat_y = int(START_Y + PLAYER_SIZE + 2)
        return Platform(start_plat_x, start_plat_y, start_plat_width, PLATFORM_HEIGHT)

    def start_run(self) -> None:
        """Initialize a new game run with reset physics, camera, and stack."""
        self.run_id += 1
        self.state = "playing"
        self.score = 0
        self.bonus_score = 0
        self.chances = CHANCES_PER_RUN
        self.player_x = float(START_X)
        self.player_y = float(START_Y)
        self.player_vx = 0.0
        self.player_vy = JUMP_VELOCITY  # Initial upward bounce
        self.start_y = float(START_Y)
        self.max_height_y = float(START_Y)
        self.camera_y = float(START_Y - (HEIGHT * CAMERA_THRESHOLD_RATIO))

        self.squash_timer = 0.0
        self.rewind_flash_timer = 0.0
        self.just_jumped = False
        self.just_boosted = False
        self.just_game_over = False

        self.hazards.clear()
        self.invuln_timer = 0.0
        self.platforms_since_hazard = 0

        self.pads.clear()
        self.crumblers.clear()
        self.debris.clear()
        self.platforms_since_pad = 999
        self.platforms_since_crumbler = 999
        self.consecutive_special_run = 0

        self.orbs.clear()
        self.events.clear()
        self.last_landing_platform = None

        self.checkpoint_stack.clear()

        # Seed initial safe platform directly under the player
        start_plat = self._make_start_platform()

        self.platforms = [start_plat]
        self.last_safe_platform = start_plat
        self.last_checkpoint_top_y = float(start_plat.top)

        # Procedurally populate platforms ahead of the player
        self._generate_platforms()

    def pause(self) -> None:
        """Pause the current run if active."""
        if self.state == "playing":
            self.state = "paused"

    def resume(self) -> None:
        """Resume gameplay from pause state."""
        if self.state == "paused":
            self.state = "playing"

    def toggle_pause(self) -> None:
        """Toggle between playing and paused."""
        if self.state == "playing":
            self.pause()
        elif self.state == "paused":
            self.resume()

    def update(self, dt: float, move_dir: int) -> None:
        """Advance the physics simulation by dt seconds with steering input [-1, 0, 1]."""
        if self.state != "playing":
            return

        # Reset per-frame audio triggers
        self.just_jumped = False
        self.just_boosted = False
        self.just_game_over = False

        # Clamp dt to prevent simulation explosion on large frame spikes
        dt = min(dt, 1.0 / 30.0)

        # Cache previous position to form swept volume for anti-tunneling
        prev_player_x = self.player_x
        prev_player_y = self.player_y

        # Update animation and effect timers
        if self.squash_timer > 0.0:
            self.squash_timer = max(0.0, self.squash_timer - dt)
        if self.rewind_flash_timer > 0.0:
            self.rewind_flash_timer = max(0.0, self.rewind_flash_timer - dt)
        if self.invuln_timer > 0.0:
            self.invuln_timer = max(0.0, self.invuln_timer - dt)

        # Update bounce pad compression timers
        for pad in self.pads:
            if pad.pressed_timer > 0.0:
                pad.pressed_timer = max(0.0, pad.pressed_timer - dt)

        # Update crumbling platform timers and drop broken platforms
        broken_platforms = []
        for c in self.crumblers:
            if c.state == "crumbling":
                c.timer = max(0.0, c.timer - dt)
                if c.timer <= 0.0:
                    c.state = "broken"
                    broken_platforms.append(c.platform)
                    self.debris.append(Debris(rect=c.platform.copy(), age=0.0))

        if broken_platforms:
            broken_ids = {id(p) for p in broken_platforms}
            self.platforms = [p for p in self.platforms if id(p) not in broken_ids]

        # Update debris lifetimes
        for d in self.debris:
            d.age += dt
        self.debris = [d for d in self.debris if d.age < DEBRIS_DURATION]

        # 1. Horizontal Movement & Screen Wrapping
        self.player_vx = move_dir * MOVE_SPEED
        self.player_x += self.player_vx * dt

        # Wrap around screen edges based on player center
        player_center_x = self.player_x + (self.player_width / 2.0)
        if player_center_x < 0.0:
            self.player_x += WIDTH
        elif player_center_x > WIDTH:
            self.player_x -= WIDTH

        # 2. Vertical Movement & Gravity
        previous_bottom = prev_player_y + self.player_height
        self.player_vy = min(self.player_vy + GRAVITY * dt, MAX_FALL_SPEED)
        self.player_y += self.player_vy * dt
        current_bottom = self.player_y + self.player_height

        # 3. Collision Detection (Linear scan over plain list)
        # Landing condition:
        # - Falling downwards (vy > 0)
        # - Player bottom crossed platform top from above (previous_bottom <= top <= current_bottom)
        # - Horizontal overlap exists
        if self.player_vy > 0:
            landing_platform: Optional[Platform] = None
            for p in self.platforms:
                # Check horizontal overlap
                if (self.player_x + self.player_width > p.left) and (self.player_x < p.right):
                    # Check vertical crossing
                    if previous_bottom <= p.top and current_bottom >= p.top:
                        # If multiple platforms are crossed in a single step, pick the highest
                        if landing_platform is None or p.top < landing_platform.top:
                            landing_platform = p

            if landing_platform is not None:
                self.last_landing_platform = landing_platform
                # Snap player bottom to platform top
                self.player_y = float(landing_platform.top - self.player_height)

                # Check for bounce pad trigger
                pad = self._platform_has_pad(landing_platform)
                pad_triggered = False
                if pad is not None:
                    # Player horizontal extent overlaps pad inflated by PAD_FORGIVENESS each side
                    pad_left = pad.rect.left - PAD_FORGIVENESS
                    pad_right = pad.rect.right + PAD_FORGIVENESS
                    if (self.player_x + self.player_width > pad_left) and (self.player_x < pad_right):
                        pad_triggered = True

                if pad_triggered:
                    assert pad is not None
                    self.player_vy = PAD_JUMP_VELOCITY
                    pad.pressed_timer = PAD_PRESS_DURATION
                    self.just_boosted = True
                    self.squash_timer = SQUASH_DURATION * 1.5
                else:
                    self.player_vy = JUMP_VELOCITY
                    self.squash_timer = SQUASH_DURATION

                self.just_jumped = True

                # Trigger crumbler timer on intact landing
                crumbler = self._get_crumbler(landing_platform)
                if crumbler is not None and crumbler.state == "intact":
                    crumbler.state = "crumbling"
                    crumbler.timer = CRUMBLE_DELAY

                # Checkpoint rule: track last_safe_platform on any plain platform landing,
                # and push a checkpoint to the Stack if higher than the last saved checkpoint.
                if self._is_plain(landing_platform):
                    self.last_safe_platform = landing_platform
                    if landing_platform.top < self.last_checkpoint_top_y:
                        self.checkpoint_stack.push(
                            (landing_platform.x, landing_platform.y, landing_platform.width, landing_platform.height)
                        )
                        self.last_checkpoint_top_y = float(landing_platform.top)

        # 4. Camera Tracking (Camera only scrolls upward during normal play)
        target_camera_y = self.player_y - (HEIGHT * CAMERA_THRESHOLD_RATIO)
        if target_camera_y < self.camera_y:
            self.camera_y = target_camera_y

        # 5. Scoring (Monotonically non-decreasing, derived from maximum height reached)
        if self.player_y < self.max_height_y:
            self.max_height_y = self.player_y
        calculated_score = int((self.start_y - self.max_height_y) / SCORE_DIVISOR)
        if calculated_score > self.score:
            self.score = calculated_score

        # 6. Procedural Generation & Pruning
        self._generate_platforms()
        self._prune_platforms()

        # 6.5. Collectible Bonus Orbs (swept bounding rect to prevent tunneling)
        min_px = min(prev_player_x, self.player_x)
        max_px = max(prev_player_x + self.player_width, self.player_x + self.player_width)
        min_py = min(prev_player_y, self.player_y)
        max_py = max(prev_player_y + self.player_height, self.player_y + self.player_height)
        player_swept = pygame.Rect(int(min_px), int(min_py), int(max_px - min_px), int(max_py - min_py))

        remaining_orbs = []
        for orb in self.orbs:
            cx = max(player_swept.left, min(player_swept.right, orb.x))
            cy = max(player_swept.top, min(player_swept.bottom, orb.y))
            dist = math.hypot(orb.x - cx, orb.y - cy)
            if dist <= orb.radius + ORB_PICKUP_FORGIVENESS:
                self.bonus_score += orb.points
                self.events.append(("orb", orb.x, orb.y, orb.points, orb.risk))
                if len(self.events) > 32:
                    self.events.pop(0)
            else:
                remaining_orbs.append(orb)
        self.orbs = remaining_orbs

        # 7. Near-Miss Evaluation & Spike Hazard Collision Detection
        player_rect = pygame.Rect(int(self.player_x), int(self.player_y), self.player_width, self.player_height)
        player_box = player_rect.inflate(-2 * PLAYER_HITBOX_INSET, -2 * PLAYER_HITBOX_INSET)

        # Check if a fatal spike collision occurs this frame
        hit_hazard: Optional[Hazard] = None
        if self.invuln_timer <= 0.0:
            for h in self.hazards:
                if player_box.colliderect(h.hitbox()):
                    hit_hazard = h
                    break

        for h in self.hazards:
            hitbox = h.hitbox()
            zone = hitbox.inflate(2 * NEAR_MISS_MARGIN, 2 * NEAR_MISS_MARGIN)

            if player_box.colliderect(hitbox):
                # Direct hit never pays out near-miss bonus
                h.near_miss_awarded = True
                h.in_zone = False
            elif (
                player_box.colliderect(zone)
                and not h.near_miss_awarded
                and (h.platform is not self.last_landing_platform)
                and self.invuln_timer <= 0.0
            ):
                h.in_zone = True
            elif h.in_zone:
                # Player has exited the close call zone without touching the spikes
                # Ordering rule: if a hit occurred anywhere this frame, handle hit only (no award)
                if (
                    hit_hazard is None
                    and (h.platform is not self.last_landing_platform)
                    and self.invuln_timer <= 0.0
                    and not h.near_miss_awarded
                ):
                    self.bonus_score += NEAR_MISS_POINTS
                    p_cx = self.player_x + self.player_width / 2.0
                    p_top = self.player_y
                    self.events.append(("near_miss", p_cx, p_top, NEAR_MISS_POINTS, False))
                    if len(self.events) > 32:
                        self.events.pop(0)
                    h.near_miss_awarded = True
                h.in_zone = False

        if hit_hazard is not None:
            self._handle_hit()
        elif self.player_y > self.camera_y + HEIGHT:
            self._handle_fall()

    def save_if_best(self, path: Path = HIGHSCORE_PATH) -> None:
        """Update best score and persist to disk if current total score exceeds it."""
        if self.total_score > self.best_score:
            self.best_score = self.total_score
            save_highscore(self.best_score, path=path)

    def _handle_hit(self) -> None:
        """Handle obstacle collision; delegates directly to _handle_fall()."""
        self._handle_fall()

    def _handle_fall(self) -> None:
        """Handle falling below visible screen or hitting an obstacle."""
        if self.state != "playing":
            return
        if self.chances > 0:
            self.chances -= 1
            self._rewind()
        else:
            self.state = "game_over"
            self.just_game_over = True
            self.save_if_best()

    def _rewind(self) -> None:
        """Execute Second Chance rewind using LIFO checkpoint stack or safe platform fallback."""
        if not self.checkpoint_stack.is_empty():
            cp_data = self.checkpoint_stack.pop()
            assert cp_data is not None
            cp_x, cp_y, cp_w, cp_h = cp_data
            cp_platform = Platform(cp_x, cp_y, cp_w, cp_h)
        elif self.last_safe_platform is not None:
            cp_platform = self.last_safe_platform
        elif self.platforms:
            candidates = [p for p in self.platforms if p.top < self.camera_y + HEIGHT]
            cp_platform = max(candidates, key=lambda p: p.top) if candidates else self.platforms[0]
        else:
            cp_platform = self._make_start_platform()

        # a. Ensure checkpoint platform exists in platforms list (re-append if culled)
        if cp_platform not in self.platforms:
            self.platforms.append(cp_platform)

        # b. Place player centered above that platform with immediate upward bounce
        self.player_x = float(cp_platform.centerx - (self.player_width / 2.0))
        self.player_y = float(cp_platform.top - self.player_height)
        self.player_vx = 0.0
        self.player_vy = JUMP_VELOCITY
        self.squash_timer = SQUASH_DURATION

        # c. Move camera so the restored platform appears at REWIND_SCREEN_RATIO of screen height
        self.camera_y = float(cp_platform.top - (HEIGHT * REWIND_SCREEN_RATIO))

        # d. Keep on-screen platforms, regenerate upwards, and re-prune
        self._generate_platforms()
        self._prune_platforms()

        # Standable check guard: guarantee platform is in list and visible
        if cp_platform not in self.platforms:
            self.platforms.append(cp_platform)

        # e. Score, max_height_y, and bonus_score MUST NOT change. Reset checkpoint baseline to restored height
        self.last_checkpoint_top_y = float(cp_platform.top)
        self.invuln_timer = REWIND_INVULN_DURATION

        # Reset in_zone flags on teleport
        for h in self.hazards:
            h.in_zone = False

        # f. Trigger rewind screen flash
        self.rewind_flash_timer = REWIND_FLASH_DURATION

        # Rewind restores crumblers: reset every tracked crumbler to "intact" (timer 0),
        # re-add its platform to self.platforms if missing (identity check, no duplicates),
        # and clear self.debris.
        # Reason: broken crumblers above the checkpoint would otherwise leave an unreachable gap in the route.
        for c in self.crumblers:
            c.state = "intact"
            c.timer = 0.0
            if not any(p is c.platform for p in self.platforms):
                self.platforms.append(c.platform)
        self.debris.clear()

    def _generate_platforms(self) -> None:
        """Generate platforms upward until reaching at least one screen above camera."""
        if not self.platforms:
            return

        highest = min(self.platforms, key=lambda p: p.top)

        # Generate platforms upward until at least one screen height above camera top
        while highest.top > self.camera_y - HEIGHT:
            difficulty = min(1.0, self.score / DIFFICULTY_RAMP_SCORE)
            current_width = int(PLATFORM_START_WIDTH - difficulty * (PLATFORM_START_WIDTH - PLATFORM_MIN_WIDTH))

            # Run limit check: at most MAX_SPECIAL_RUN consecutive non-plain platforms
            force_plain = (self.consecutive_special_run >= MAX_SPECIAL_RUN)
            if len(self.platforms) < 4:
                force_plain = True

            # Hazard eligibility calculation
            hazard_level = (
                max(0.0, min(1.0, (self.score - SPIKE_START_SCORE) / (HAZARD_FULL_SCORE - SPIKE_START_SCORE)))
                if self.score >= SPIKE_START_SCORE
                else 0.0
            )
            clean_gap = round(HAZARD_CLEAN_GAP_START - hazard_level * (HAZARD_CLEAN_GAP_START - HAZARD_CLEAN_GAP_FINAL))
            can_hazard = (
                self.hazards_enabled
                and (self.platforms_since_hazard >= clean_gap)
                and (self.platforms_since_pad >= PAD_CLEAR_PLATFORMS)
                and (not force_plain)
            )

            # Decide spike BEFORE positioning to ensure width guarantee
            spike_chance = SPIKE_CHANCE_START + hazard_level * (SPIKE_CHANCE_FINAL - SPIKE_CHANCE_START)
            is_spike = can_hazard and (self.score >= SPIKE_START_SCORE) and (random.random() < spike_chance)

            if is_spike:
                current_width = max(current_width, SPIKE_PLATFORM_MIN_WIDTH)

            # Difficulty-scaled vertical gap, capped at MAX_GAP_LIMIT
            min_gap = GAP_START_MIN + difficulty * (GAP_FINAL_MIN - GAP_START_MIN)
            max_gap = GAP_START_MAX + difficulty * (GAP_FINAL_MAX - GAP_START_MAX)
            max_gap = min(max_gap, MAX_GAP_LIMIT)

            # Integer gap strictly within bounds
            gap = random.randint(int(min_gap), int(max_gap))
            new_top = highest.top - gap

            # Forced minimum horizontal offset ramping with difficulty
            min_dx = MIN_DX_START + difficulty * (MIN_DX_FINAL - MIN_DX_START)
            dx = random.uniform(min_dx, MAX_DX - 1.0)

            # Direction choice with anti-pattern bias (avoid 3 in a row in same direction)
            chosen_dir = random.choice((-1, 1))
            if len(self.platforms) >= 3:
                d1 = self.platforms[-1].centerx - self.platforms[-2].centerx
                d2 = self.platforms[-2].centerx - self.platforms[-3].centerx
                if d1 > 0 and d2 > 0:
                    chosen_dir = -1
                elif d1 < 0 and d2 < 0:
                    chosen_dir = 1

            prev_center_x = highest.centerx
            min_valid_center = current_width / 2.0
            max_valid_center = WIDTH - (current_width / 2.0)

            new_center = prev_center_x + chosen_dir * dx
            if new_center < min_valid_center or new_center > max_valid_center:
                # Flip to opposite direction
                new_center = prev_center_x - chosen_dir * dx
                if new_center < min_valid_center or new_center > max_valid_center:
                    # Clamp to valid range if flipped is also out of bounds
                    new_center = max(min_valid_center, min(max_valid_center, new_center))

            new_x = int(round(new_center - current_width / 2.0))
            new_x = max(0, min(WIDTH - current_width, new_x))

            new_plat = Platform(new_x, new_top, current_width, PLATFORM_HEIGHT)
            self.platforms.append(new_plat)

            # Drop any existing orb that overlaps the new platform (inflated by ORB_CLEARANCE)
            plat_clear_rect = new_plat.inflate(2 * ORB_CLEARANCE, 2 * ORB_CLEARANCE)
            self.orbs = [
                orb for orb in self.orbs
                if not self._circle_overlaps_rect(orb.x, orb.y, orb.radius, plat_clear_rect)
            ]

            hazard_placed = False
            pad_placed = False
            crumbler_placed = False

            if is_spike:
                # Place spike strip on random end
                on_left = random.choice((True, False))
                strip_w = int(new_plat.width * SPIKE_COVERAGE)
                strip_x = new_plat.left if on_left else (new_plat.right - strip_w)
                strip_y = new_plat.top - SPIKE_HEIGHT
                strip_rect = pygame.Rect(strip_x, strip_y, strip_w, SPIKE_HEIGHT)
                self.hazards.append(Hazard(platform=new_plat, rect=strip_rect))
                hazard_placed = True

                # Risk orb placement above spike strip
                if self.orbs_enabled and (self.score >= ORB_START_SCORE) and len(self.platforms) >= 4:
                    if random.random() < RISK_ORB_CHANCE:
                        risk_radius = float(RISK_ORB_RADIUS)
                        risk_x = float(strip_rect.centerx)
                        if risk_radius + 8.0 <= risk_x <= WIDTH - (risk_radius + 8.0):
                            risk_y = float(new_plat.top - SPIKE_HEIGHT - RISK_ORB_HEIGHT)
                            if self._orb_is_clear(risk_x, risk_y, risk_radius):
                                self.orbs.append(
                                    Orb(x=risk_x, y=risk_y, radius=risk_radius, points=RISK_ORB_POINTS, risk=True)
                                )
            elif self.specials_enabled and not force_plain:
                # Roll for bounce pad if score >= PAD_START_SCORE
                if self.score >= PAD_START_SCORE:
                    special_level_pad = min(1.0, max(0.0, (self.score - PAD_START_SCORE) / (HAZARD_FULL_SCORE - PAD_START_SCORE)))
                    pad_chance = PAD_CHANCE_START + special_level_pad * (PAD_CHANCE_FINAL - PAD_CHANCE_START)
                    if random.random() < pad_chance:
                        pad_center_min = new_plat.left + PAD_WIDTH / 2.0
                        pad_center_max = new_plat.right - PAD_WIDTH / 2.0
                        if pad_center_min <= pad_center_max:
                            pad_cx = random.uniform(pad_center_min, pad_center_max)
                            pad_x = int(round(pad_cx - PAD_WIDTH / 2.0))
                            pad_x = max(new_plat.left, min(new_plat.right - PAD_WIDTH, pad_x))
                            pad_y = new_plat.top - PAD_HEIGHT
                            pad_rect = pygame.Rect(pad_x, pad_y, PAD_WIDTH, PAD_HEIGHT)
                            self.pads.append(Pad(platform=new_plat, rect=pad_rect))
                            pad_placed = True

                # If no pad, roll for crumbler if score >= CRUMBLE_START_SCORE and min plain gap respected
                if (not pad_placed) and (self.score >= CRUMBLE_START_SCORE) and (self.platforms_since_crumbler >= CRUMBLE_MIN_PLAIN_BETWEEN):
                    special_level_crumble = min(1.0, max(0.0, (self.score - CRUMBLE_START_SCORE) / (HAZARD_FULL_SCORE - CRUMBLE_START_SCORE)))
                    crumble_chance = CRUMBLE_CHANCE_START + special_level_crumble * (CRUMBLE_CHANCE_FINAL - CRUMBLE_CHANCE_START)
                    if random.random() < crumble_chance:
                        self.crumblers.append(Crumbler(platform=new_plat, state="intact", timer=0.0))
                        crumbler_placed = True

                # Normal orb placement in the gap between lower (highest) and upper (new_plat)
                if self.orbs_enabled and (self.score >= ORB_START_SCORE) and len(self.platforms) >= 4:
                    if random.random() < ORB_CHANCE:
                        lower = highest
                        upper = new_plat
                        t = random.uniform(0.3, 0.7)
                        raw_x = lower.centerx + t * (upper.centerx - lower.centerx)
                        norm_radius = float(ORB_RADIUS)
                        orb_x = max(norm_radius + 8.0, min(WIDTH - (norm_radius + 8.0), raw_x))
                        free_space = lower.top - upper.bottom
                        if free_space > 0:
                            orb_y = upper.bottom + random.uniform(0.35, 0.65) * free_space
                            if self._orb_is_clear(orb_x, orb_y, norm_radius):
                                self.orbs.append(
                                    Orb(x=orb_x, y=orb_y, radius=norm_radius, points=ORB_POINTS, risk=False)
                                )

            # Update tracking counters
            if is_spike or pad_placed or crumbler_placed:
                self.consecutive_special_run += 1
            else:
                self.consecutive_special_run = 0

            if pad_placed:
                self.platforms_since_pad = 0
            else:
                self.platforms_since_pad += 1

            if crumbler_placed:
                self.platforms_since_crumbler = 0
            else:
                self.platforms_since_crumbler += 1

            if hazard_placed:
                self.platforms_since_hazard = 0
            else:
                self.platforms_since_hazard += 1

            highest = new_plat

    def _prune_platforms(self) -> None:
        """Remove platforms, orbs, and obstacles fallen below camera window, bounded by oldest checkpoint or safe platform."""
        # Prune safety invariant: nothing at or above the oldest checkpoint in the Stack or last_safe_platform is pruned.
        # Using the identical cutoff for platforms, pads, crumblers, hazards, debris, and orbs ensures
        # no feature or hazard is pruned while its underlying platform survives.
        cutoff = self.camera_y + HEIGHT + PRUNE_MARGIN
        lowest_protect_y: Optional[float] = None
        if not self.checkpoint_stack.is_empty():
            oldest_checkpoint = self.checkpoint_stack.to_list()[0]
            lowest_protect_y = float(oldest_checkpoint[1])
        if self.last_safe_platform is not None:
            safe_y = float(self.last_safe_platform.y)
            if lowest_protect_y is None or safe_y > lowest_protect_y:
                lowest_protect_y = safe_y

        if lowest_protect_y is not None:
            cutoff = max(cutoff, lowest_protect_y + PLATFORM_HEIGHT + 1)

        self.platforms = [p for p in self.platforms if p.top < cutoff]
        self.hazards = [h for h in self.hazards if h.platform.top < cutoff]
        self.pads = [pad for pad in self.pads if pad.platform.top < cutoff]
        self.crumblers = [c for c in self.crumblers if c.platform.top < cutoff]
        self.debris = [d for d in self.debris if d.rect.top < cutoff]
        self.orbs = [orb for orb in self.orbs if (orb.y - orb.radius) < cutoff]
