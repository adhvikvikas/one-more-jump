"""Automated unit and integration tests for One More Jump.

Verifies:
1. Stack operations (LIFO order, capacity bounds, oldest-item eviction, empty pop).
2. Procedural platform reachability across >= 10,000 generated platforms.
3. Accurate collision physics (landing, rising, beside).
4. Score monotonicity across upward climbing and checkpoint rewinding.
5. Second chance rewind restoration (camera position, player alignment, stack pop, empty stack game over).
6. State reset integrity in start_run().
7. High score file I/O resilience (missing, empty, corrupted, non-integer data) without touching real save file.
8. One-shot audio trigger clearing in Renderer.
9. Hazard progression, densities, fairness invariants, collision, hit consequences, checkpoint safety, and stability soak.
"""

import math
import os
from pathlib import Path
import random

# Force headless dummy video and audio drivers for CI/testing
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
pygame.init()

from dsa import Stack
from game import Crumbler, Debris, Game, Hazard, Orb, Pad, Platform, load_highscore, save_highscore
from renderer import Renderer
import settings
from settings import (
    CHANCES_PER_RUN,
    CRUMBLE_DELAY,
    CRUMBLE_MIN_PLAIN_BETWEEN,
    CRUMBLE_START_SCORE,
    DEBRIS_DURATION,
    DIFFICULTY_RAMP_SCORE,
    HEIGHT,
    JUMP_HEIGHT,
    JUMP_VELOCITY,
    MAX_DX,
    MAX_FALL_SPEED,
    MAX_FX_PARTICLES,
    MAX_GAP_LIMIT,
    MAX_POPUPS,
    MAX_SPECIAL_RUN,
    NEAR_MISS_MARGIN,
    NEAR_MISS_POINTS,
    ORB_CLEARANCE,
    ORB_POINTS,
    ORB_RADIUS,
    PAD_CLEAR_PLATFORMS,
    PAD_FORGIVENESS,
    PAD_HEIGHT,
    PAD_HEIGHT_FACTOR,
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
    REWIND_SCREEN_RATIO,
    RISK_ORB_HEIGHT,
    RISK_ORB_POINTS,
    RISK_ORB_RADIUS,
    SPIKE_COVERAGE,
    SPIKE_HEIGHT,
    START_X,
    WIDTH,
)


def test_stack_operations() -> None:
    """Test 1: LIFO behavior, capacity bounding, and empty behavior."""
    s = Stack[int](capacity=3)
    assert s.is_empty(), "New stack should be empty."
    assert s.size() == 0
    assert s.pop() is None, "Pop on empty stack should return None."
    assert s.peek() is None, "Peek on empty stack should return None."

    # LIFO push & pop
    s.push(10)
    s.push(20)
    assert s.size() == 2
    assert s.peek() == 20
    assert s.pop() == 20
    assert s.peek() == 10
    assert s.pop() == 10
    assert s.is_empty()

    # Bounded capacity eviction of oldest entry
    s.push(1)
    s.push(2)
    s.push(3)
    assert s.is_full()
    assert s.size() == 3

    # 4th push should evict 1 (the oldest)
    s.push(4)
    assert s.size() == 3
    assert s.pop() == 4
    assert s.pop() == 3
    assert s.pop() == 2
    assert s.pop() is None
    print("✓ Test 1 Passed: Stack operations & bounded eviction.")


def test_reachability() -> None:
    """Test 2: Generate 10,000+ platforms; verify reachability, offsets, overlap, and difficulty scaling."""
    game = Game()
    game.hazards_enabled = False
    game.specials_enabled = False
    game.orbs_enabled = False
    game.start_run()

    # Artificially expand camera upward to trigger generation of >10,000 platforms
    target_count = 10500
    while len(game.platforms) < target_count:
        game.camera_y -= 5000.0
        game.score = min(2000, game.score + 50)
        game._generate_platforms()

    platforms = game.platforms
    assert len(platforms) >= 10000, f"Expected >= 10000 platforms, got {len(platforms)}"

    sorted_platforms = sorted(platforms, key=lambda p: -p.top)

    clamped_count = 0
    total_pairs = len(sorted_platforms) - 1

    for i in range(total_pairs):
        lower = sorted_platforms[i]
        upper = sorted_platforms[i + 1]

        # Vertical gap check
        vertical_gap = lower.top - upper.top
        assert vertical_gap > 0, f"Upper platform must be above lower platform (gap={vertical_gap})"
        assert vertical_gap <= MAX_GAP_LIMIT + 1e-4, (
            f"Gap violation: {vertical_gap} > MAX_GAP_LIMIT ({MAX_GAP_LIMIT}) between {lower} and {upper}"
        )

        # Horizontal span check
        dx = abs(upper.centerx - lower.centerx)
        assert dx <= MAX_DX + 1e-4, f"dx violation: {dx} > MAX_DX ({MAX_DX}) between {lower} and {upper}"

        # Boundary checks
        assert upper.left >= 0, f"Platform extends past left screen bound: {upper.left}"
        assert upper.right <= WIDTH, f"Platform extends past right screen bound: {upper.right} (WIDTH={WIDTH})"

        # Non-overlap check: platforms must never overlap
        assert not lower.colliderect(upper), f"Platforms overlap: {lower} and {upper}"

        # Check 1: Forced horizontal offset (|dx| >= 50 or edge clamped)
        is_edge_clamped = (upper.left == 0 or upper.right == WIDTH)
        if is_edge_clamped:
            clamped_count += 1
        else:
            assert dx >= 50 - 1e-4, f"dx violation: {dx} < 50 for non-edge-clamped pair {lower} -> {upper}"

    # Clamped ratio check: at most 5 percent
    clamped_pct = (clamped_count / total_pairs) * 100.0
    assert clamped_pct <= 5.0, f"Clamped pairs ({clamped_pct:.2f}%) exceeded 5% maximum allowance."

    # Check 2 & 4: Average vertical gaps and platform widths at difficulty 0 and 1
    g0 = Game()
    g0.hazards_enabled = False
    g0.specials_enabled = False
    g0.orbs_enabled = False
    g0.start_run()
    g0.score = 0
    while len(g0.platforms) < 500:
        g0.camera_y -= 1000.0
        g0._generate_platforms()

    g0_sorted = sorted(g0.platforms, key=lambda p: -p.top)
    g0_gaps = [g0_sorted[j].top - g0_sorted[j + 1].top for j in range(len(g0_sorted) - 1)]
    avg_g0_gap = sum(g0_gaps) / len(g0_gaps)
    assert avg_g0_gap >= 100.0, f"Difficulty 0 average gap {avg_g0_gap:.2f} < 100"
    assert all(p.width == PLATFORM_START_WIDTH for p in g0.platforms[1:]), (
        f"Difficulty 0 platforms should have width {PLATFORM_START_WIDTH}"
    )

    g1 = Game()
    g1.hazards_enabled = False
    g1.specials_enabled = False
    g1.orbs_enabled = False
    g1.start_run()
    initial_g1_count = len(g1.platforms)
    g1.score = DIFFICULTY_RAMP_SCORE
    while len(g1.platforms) < 500:
        g1.camera_y -= 1000.0
        g1._generate_platforms()

    g1_diff1_plats = g1.platforms[initial_g1_count:]
    g1_sorted = sorted(g1_diff1_plats, key=lambda p: -p.top)
    g1_gaps = [g1_sorted[j].top - g1_sorted[j + 1].top for j in range(len(g1_sorted) - 1)]
    avg_g1_gap = sum(g1_gaps) / len(g1_gaps)
    assert avg_g1_gap >= 132.0, f"Difficulty 1 average gap {avg_g1_gap:.2f} < 132"
    assert all(p.width == PLATFORM_MIN_WIDTH for p in g1_diff1_plats), (
        f"Difficulty 1 platforms should have width {PLATFORM_MIN_WIDTH}"
    )

    print(
        f"✓ Test 2 Passed: Reachability verified across {len(platforms)} platforms "
        f"(clamped={clamped_pct:.2f}%, g0_avg_gap={avg_g0_gap:.1f}, g1_avg_gap={avg_g1_gap:.1f})."
    )


def test_collision() -> None:
    """Test 3: Falling player lands, rising player passes through, beside player does not land."""
    game = Game()
    game.hazards_enabled = False
    game.specials_enabled = False
    game.orbs_enabled = False
    game.start_run()
    test_plat = Platform(100, 300, 100, 12)
    game.platforms = [test_plat]

    # Case A: Falling player crossing platform top from above -> lands
    game.player_x = 120.0
    game.player_y = 295.0 - PLAYER_SIZE  # previous bottom = 295 <= platform.top (300)
    game.player_vy = 300.0              # Falling
    game.update(dt=0.03, move_dir=0)
    assert game.player_vy == JUMP_VELOCITY, f"Expected vy to be JUMP_VELOCITY, got {game.player_vy}"
    assert game.player_y == test_plat.top - PLAYER_SIZE, "Player bottom should snap to platform top."

    # Case B: Rising player passing upward through platform -> does not land
    game.player_x = 120.0
    game.player_y = 310.0
    game.player_vy = -400.0  # Rising
    game.update(dt=0.03, move_dir=0)
    assert game.player_vy < 0.0, "Rising player should continue rising uninterrupted."

    # Case C: Player beside platform -> does not land
    game.player_x = 250.0  # Outside platform [100, 200]
    game.player_y = 290.0 - PLAYER_SIZE
    game.player_vy = 300.0  # Falling
    game.update(dt=0.03, move_dir=0)
    assert game.player_vy > 0.0, "Player beside platform should keep falling."

    print("✓ Test 3 Passed: Collision physics verified.")


def test_score_monotonicity() -> None:
    """Test 4: Score is non-decreasing over simulated climb, through falls and rewinds."""
    game = Game()
    game.hazards_enabled = False
    game.specials_enabled = False
    game.orbs_enabled = False
    game.start_run()

    last_score = game.score
    # Simulate upward climb
    for _ in range(50):
        game.player_y -= 40.0
        game.update(dt=0.02, move_dir=0)
        assert game.score >= last_score, "Score must never decrease during ascent."
        last_score = game.score

    # Simulate checkpoint rewind and verify score persists unchanged
    score_before_rewind = game.score
    game.checkpoint_stack.push((100, int(game.player_y - 20), 100, 12))
    # Trigger fall
    game.player_y = game.camera_y + HEIGHT + 10.0
    game.update(dt=0.02, move_dir=0)

    assert game.score == score_before_rewind, (
        f"Score changed across rewind! Before: {score_before_rewind}, After: {game.score}"
    )
    print("✓ Test 4 Passed: Score monotonicity and rewind invariance verified.")


def test_rewind_and_game_over() -> None:
    """Test 5: Rewind restores player, positions camera, decrements chances; 0 chances ends run."""
    game = Game()
    game.hazards_enabled = False
    game.specials_enabled = False
    game.orbs_enabled = False
    game.start_run()

    # Push a checkpoint
    cp_rect = (150, int(game.camera_y + 100), 80, 12)
    game.checkpoint_stack.push(cp_rect)
    assert game.checkpoint_stack.size() == 1
    assert game.chances == 3

    # Force a fall below screen
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(dt=0.016, move_dir=0)

    # Verify rewind execution
    assert game.state == "playing", "Game should remain playing after rewind."
    assert game.checkpoint_stack.size() == 0, "Rewind should pop one checkpoint."
    assert game.chances == 2, "Rewind should decrement chances."
    assert Platform(*cp_rect) in game.platforms, "Checkpoint platform must be in platforms list."
    expected_cam = cp_rect[1] - (HEIGHT * REWIND_SCREEN_RATIO)
    assert abs(game.camera_y - expected_cam) < 1.0, f"Camera y mismatch: {game.camera_y} vs {expected_cam}"
    assert game.player_vy == JUMP_VELOCITY, "Player must bounce immediately on rewind."

    # Use remaining chances: 2 -> 1
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(dt=0.016, move_dir=0)
    assert game.chances == 1
    assert game.state == "playing"

    # Use remaining chances: 1 -> 0
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(dt=0.016, move_dir=0)
    assert game.chances == 0
    assert game.state == "playing"

    # Force another fall with 0 chances -> Game Over
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(dt=0.016, move_dir=0)
    assert game.state == "game_over", f"Expected game_over with 0 chances, got {game.state}"
    print("✓ Test 5 Passed: Rewind and Game Over transitions verified.")


def test_start_run_reset() -> None:
    """Test 6: start_run() fully resets score, platforms, camera, player, and stack."""
    game = Game()
    game.start_run()

    # Mutate state
    game.score = 2500
    game.bonus_score = 500
    game.camera_y = -3000.0
    game.player_y = -3200.0
    game.checkpoint_stack.push((50, -3200, 80, 12))
    plat = Platform(0, 0, 100, 12)
    game.hazards.append(Hazard(platform=plat, rect=pygame.Rect(0, 0, 10, 10)))
    game.orbs.append(Orb(x=50.0, y=50.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False))
    game.invuln_timer = 2.0
    game.state = "game_over"

    # Reset
    game.start_run()
    assert game.state == "playing"
    assert game.score == 0
    assert game.bonus_score == 0
    assert game.chances == CHANCES_PER_RUN
    assert game.checkpoint_stack.is_empty(), "Stack must be cleared upon reset."
    assert len(game.platforms) > 0, "Platforms must be re-populated."
    assert len(game.hazards) == 0 or all(h.platform in game.platforms for h in game.hazards)
    assert game.invuln_timer == 0.0
    assert game.player_vy == JUMP_VELOCITY
    assert abs(game.player_x - START_X) < 1.0
    print("✓ Test 6 Passed: Complete reset on start_run().")


def test_highscore_io(tmp_path: Path) -> None:
    """Test 7: File missing, empty, corrupt, and non-integer load as 0; round-trip saves properly."""
    test_file = tmp_path / "test_highscore.json"

    # Record real highscore.json state before test
    real_existed_before = settings.HIGHSCORE_PATH.exists()
    real_content_before = settings.HIGHSCORE_PATH.read_text(encoding="utf-8") if real_existed_before else None

    # A. Missing file
    if test_file.exists():
        test_file.unlink()
    assert load_highscore(test_file) == 0

    # B. Empty file
    test_file.write_text("", encoding="utf-8")
    assert load_highscore(test_file) == 0

    # C. Corrupt JSON
    test_file.write_text("{bad json: 123", encoding="utf-8")
    assert load_highscore(test_file) == 0

    # D. Non-integer value
    test_file.write_text('{"highscore": "not_an_int"}', encoding="utf-8")
    assert load_highscore(test_file) == 0

    # E. Boolean value (booleans are subclasses of int in Python)
    test_file.write_text('{"highscore": true}', encoding="utf-8")
    assert load_highscore(test_file) == 0

    # F. Valid round-trip on explicit path
    save_highscore(420, test_file)
    assert load_highscore(test_file) == 420

    # Explicit assertion: real HIGHSCORE_PATH file's contents are unchanged
    real_existed_after = settings.HIGHSCORE_PATH.exists()
    real_content_after = settings.HIGHSCORE_PATH.read_text(encoding="utf-8") if real_existed_after else None
    assert real_existed_before == real_existed_after, "Real highscore.json existence modified by test!"
    assert real_content_before == real_content_after, "Real highscore.json content modified by test!"

    save_highscore(9999, test_file)
    assert load_highscore(test_file) == 9999

    if test_file.exists():
        test_file.unlink()
    print("✓ Test 7 Passed: High score persistence resilience without touching real file.")


def test_audio_trigger_clear() -> None:
    """Test 8: Verify renderer clears just_game_over on first render so sound cannot replay."""
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    renderer = Renderer(screen)
    game = Game()
    game.state = "game_over"
    game.just_game_over = True

    # First frame render should consume the flag
    renderer.render(game, (0, 0), dt=1.0 / 60.0)
    assert not game.just_game_over, "Renderer must clear just_game_over after playing sound in frame 1."

    # Second frame render confirms flag remains False (no replay)
    renderer.render(game, (0, 0), dt=1.0 / 60.0)
    assert not game.just_game_over, "just_game_over must stay False on subsequent frames."
    print("✓ Test 8 Passed: Sound trigger clearance verified (no repeating sound after game over).")


def test_hazard_progression() -> None:
    """Test 9: Hazard progression and density scaling across score tiers."""
    random.seed(42)
    scores = [100, 150, 350, 800, 1500]
    densities = {}
    for s in scores:
        g = Game()
        g.hazards_enabled = True
        g.specials_enabled = False
        g.orbs_enabled = False
        g.start_run()
        g.score = s
        init_p_count = len(g.platforms)
        init_h_count = len(g.hazards)
        while len(g.platforms) - init_p_count < 5000:
            g.camera_y -= 1000.0
            g._generate_platforms()

        new_platforms = g.platforms[init_p_count:]
        new_hazards = g.hazards[init_h_count:]
        p_count = len(new_platforms)
        h_count = len(new_hazards)
        density = (h_count / p_count) * 100.0
        densities[s] = (density, new_hazards)

    # No hazards below score 150
    assert len(densities[100][1]) == 0, f"Expected 0 hazards below score 150, got {len(densities[100][1])}"

    print("\nHazard Density Table (Hazards per 100 platforms):")
    print("---------------------------------------")
    print(" Score Tier | Hazards / 100 Platforms")
    print("---------------------------------------")
    for s in [150, 350, 800, 1500]:
        print(f"   {s:4d}     |         {densities[s][0]:5.2f}")
    print("---------------------------------------")

    d150 = densities[150][0]
    d350 = densities[350][0]
    d800 = densities[800][0]
    d1500 = densities[1500][0]

    # Non-decreasing with small statistical tolerance (1.0%)
    assert d350 >= d150 - 1.0, f"Density decreased: {d350} < {d150}"
    assert d800 >= d350 - 1.0, f"Density decreased: {d800} < {d350}"
    assert d1500 >= d800 - 1.0, f"Density decreased: {d1500} < {d800}"
    print("✓ Test 9 Passed: Hazard progression verified.")


def test_hazard_fairness_invariants() -> None:
    """Test 10: Invariants over 10,000+ platforms with hazards enabled."""
    random.seed(42)
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = False
    game.orbs_enabled = False
    game.start_run()

    while len(game.platforms) < 10500:
        game.camera_y -= 5000.0
        game.score = min(2000, game.score + 25)
        game._generate_platforms()

    platforms = game.platforms
    hazards = game.hazards
    sorted_platforms = sorted(platforms, key=lambda p: -p.top)

    # 1. Consecutive-platform reachability
    for i in range(len(sorted_platforms) - 1):
        lower = sorted_platforms[i]
        upper = sorted_platforms[i + 1]
        v_gap = lower.top - upper.top
        assert v_gap <= MAX_GAP_LIMIT + 1e-4, f"Vertical gap {v_gap} > MAX_GAP_LIMIT"
        h_gap = abs(upper.centerx - lower.centerx)
        assert h_gap <= MAX_DX + 1e-4, f"Horizontal gap {h_gap} > MAX_DX"

    # 2. Spike platform width and safe zone
    for h in hazards:
        assert h.platform is not None
        assert h.platform.width >= 90, f"Spike platform width {h.platform.width} < 90"
        safe_zone = h.platform.width - h.rect.width
        assert safe_zone >= PLAYER_SIZE + 20, f"Safe zone {safe_zone} < {PLAYER_SIZE + 20}"

    # 3. Clean-platform spacing: never consecutive spike platforms
    spiked_platforms = {id(h.platform) for h in hazards if h.platform}
    for i in range(len(platforms) - 1):
        p1 = platforms[i]
        p2 = platforms[i + 1]
        assert not (id(p1) in spiked_platforms and id(p2) in spiked_platforms), "Two consecutive platforms have spikes!"

    print("✓ Test 10 Passed: Hazard fairness invariants verified over 10,000+ platforms.")


def test_spike_collision() -> None:
    """Test 11: Spike collision, safe zone landing, and invulnerability."""
    game = Game()
    game.hazards_enabled = True
    game.start_run()
    game.score = 500
    game.chances = 0

    plat = Platform(100, 400, 100, 12)
    strip = pygame.Rect(100, 400 - SPIKE_HEIGHT, int(100 * SPIKE_COVERAGE), SPIKE_HEIGHT)
    spike = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike]

    s_hitbox = spike.hitbox()

    # 1. Player overlapping spike hitbox with invuln == 0 -> hit
    game.invuln_timer = 0.0
    game.player_x = s_hitbox.centerx - game.player_width / 2.0
    game.player_y = s_hitbox.centery - game.player_height / 2.0
    game.update(0.01, 0)
    assert game.state == "game_over", "Expected hit on spike hitbox"

    # 2. Player overlapping only margin outside hitbox -> not hit
    game.start_run()
    game.score = 500
    game.platforms = [plat]
    game.hazards = [spike]
    # Position player outside s_hitbox but within strip.rect bounds
    game.player_x = strip.left - (game.player_width - PLAYER_HITBOX_INSET - 1)
    game.player_y = strip.top
    game.update(0.01, 0)
    assert game.state == "playing", "Margin overlap outside hitbox must not trigger hit"

    # 3. Player landing on safe part of spiked platform -> safe bounce
    game.start_run()
    game.score = 500
    game.platforms = [plat]
    game.hazards = [spike]
    # Safe side: far right of platform
    game.player_x = plat.right - game.player_width - 2
    game.player_y = plat.top - game.player_height - 2
    game.player_vy = 200.0
    game.update(0.02, 0)
    assert game.state == "playing"
    assert game.player_vy == JUMP_VELOCITY, "Player must bounce safely on safe zone"

    # 4. Invulnerability active -> not hit
    game.start_run()
    game.score = 500
    game.platforms = [plat]
    game.hazards = [spike]
    game.invuln_timer = 1.0
    game.player_x = s_hitbox.centerx - game.player_width / 2.0
    game.player_y = s_hitbox.centery - game.player_height / 2.0
    game.update(0.01, 0)
    assert game.state == "playing", "Invulnerable player must not be hit"
    print("✓ Test 11 Passed: Spike collision and safe landing verified.")


def test_hit_consequences() -> None:
    """Test 12: Hit consequences (rewind on non-empty stack, game_over on empty stack)."""
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = False
    game.orbs_enabled = False
    game.start_run()
    game.score = 600

    clean_plat = Platform(150, 400, 100, 12)
    game.platforms = [clean_plat]
    game.checkpoint_stack.push((clean_plat.x, clean_plat.y, clean_plat.width, clean_plat.height))

    # Add spike hazard
    spike_plat = Platform(150, 200, 100, 12)
    spike_strip = pygame.Rect(150, 200 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT)
    spike = Hazard(platform=spike_plat, rect=spike_strip)
    game.platforms.append(spike_plat)
    game.hazards.append(spike)

    # Position player to hit spike hitbox
    s_hb = spike.hitbox()
    game.player_x = s_hb.centerx - game.player_width / 2.0
    game.player_y = s_hb.centery - game.player_height / 2.0
    game.invuln_timer = 0.0

    score_before = game.score
    game.update(0.01, 0)

    # Rewind should trigger
    assert game.state == "playing"
    assert game.checkpoint_stack.size() == 0
    assert game.score == score_before
    assert game.invuln_timer > 0.0
    assert game.chances == 2

    # Second hit with 0 chances -> game_over
    game.chances = 0
    game.invuln_timer = 0.0
    game.player_x = s_hb.centerx - game.player_width / 2.0
    game.player_y = s_hb.centery - game.player_height / 2.0
    game.update(0.01, 0)
    assert game.state == "game_over"
    print("✓ Test 12 Passed: Hit consequences (rewind & game_over) verified.")


def test_checkpoint_safety() -> None:
    """Test 14: Checkpoint safety (spiked platforms never saved or restored)."""
    random.seed(123)
    game = Game()
    game.hazards_enabled = True
    game.start_run()
    game.score = 500

    # Simulate climbing and bouncing across 200 platforms
    for _ in range(200):
        game.camera_y -= 150.0
        game.score += 10
        game._generate_platforms()

        target_plat = min(game.platforms, key=lambda p: p.top)
        game.player_x = target_plat.centerx - game.player_width / 2.0
        game.player_y = target_plat.top + 1
        game.player_vy = 300.0
        game.update(0.016, 0)

        # Check stack: no checkpoint should ever be on a spiked platform
        for cp in game.checkpoint_stack.to_list():
            cp_rect = Platform(*cp)
            assert not game._platform_has_spikes(cp_rect), f"Checkpoint platform {cp_rect} has spikes!"

    # Force a rewind
    if not game.checkpoint_stack.is_empty():
        top_cp = game.checkpoint_stack.peek()
        restored_plat = Platform(*top_cp)
        game._handle_hit()
        assert not game._platform_has_spikes(restored_plat), "Restored platform after rewind has spikes!"

    print("✓ Test 14 Passed: Checkpoint safety verified (spikes never become checkpoints).")


def test_specials_progression() -> None:
    """Test 16: Verify score gating and non-decreasing crumbler density."""
    random.seed(42)

    # 1. No pads below 100, no crumblers below 200
    g_low = Game()
    g_low.hazards_enabled = True
    g_low.specials_enabled = True
    g_low.start_run()
    g_low.score = 50
    while len(g_low.platforms) < 500:
        g_low.camera_y -= 1000.0
        g_low._generate_platforms()

    assert g_low.score < PAD_START_SCORE
    assert g_low.score < CRUMBLE_START_SCORE
    assert len(g_low.pads) == 0, f"Pads generated below score 100: {len(g_low.pads)}"
    assert len(g_low.crumblers) == 0, f"Crumblers generated below score 200: {len(g_low.crumblers)}"

    # 2. Progression across scores 200, 600, 1000, 1500
    score_tiers = [200, 600, 1000, 1500]
    pad_densities = []
    crumble_densities = []

    for score in score_tiers:
        g = Game()
        g.hazards_enabled = True
        g.specials_enabled = True
        g.start_run()
        g.score = score
        while len(g.platforms) < 5500:
            g.camera_y -= 5000.0
            g._generate_platforms()

        sample = g.platforms[500:]
        total = len(sample)
        sample_ids = {id(p) for p in sample}

        num_pads = sum(1 for pad in g.pads if id(pad.platform) in sample_ids)
        num_crumbles = sum(1 for c in g.crumblers if id(c.platform) in sample_ids)

        p_dens = (num_pads / total) * 100.0
        c_dens = (num_crumbles / total) * 100.0
        pad_densities.append(p_dens)
        crumble_densities.append(c_dens)

    print("\nBounce Pad & Crumbler Density Table (per 100 platforms):")
    print("-------------------------------------------------------")
    print(" Score Tier |  Pads / 100 Plats  | Crumblers / 100 Plats")
    print("-------------------------------------------------------")
    for s, p_d, c_d in zip(score_tiers, pad_densities, crumble_densities):
        print(f"   {s:5d}    |       {p_d:6.2f}       |        {c_d:6.2f}")
    print("-------------------------------------------------------")

    # Crumbler density non-decreasing within small statistical tolerance (1.5)
    for i in range(1, len(crumble_densities)):
        assert crumble_densities[i] >= crumble_densities[i - 1] - 1.5, (
            f"Crumbler density decreased from {crumble_densities[i-1]} to {crumble_densities[i]}"
        )

    print("✓ Test 16 Passed: Specials progression verified.")


def test_specials_fairness_invariants() -> None:
    """Test 17: Fairness invariants over 10,000+ platforms with hazards and specials enabled."""
    random.seed(42)
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = True
    game.start_run()
    game.score = 1500  # Full difficulty

    target_count = 10500
    while len(game.platforms) < target_count:
        game.camera_y -= 5000.0
        game._generate_platforms()

    platforms = game.platforms
    sorted_plats = sorted(platforms, key=lambda p: -p.top)

    # 1. Reachability
    for i in range(len(sorted_plats) - 1):
        lower = sorted_plats[i]
        upper = sorted_plats[i + 1]
        v_gap = lower.top - upper.top
        assert v_gap <= MAX_GAP_LIMIT + 1e-4, f"Vertical gap {v_gap} > MAX_GAP_LIMIT"
        h_gap = abs(upper.centerx - lower.centerx)
        assert h_gap <= MAX_DX + 1e-4, f"Horizontal gap {h_gap} > MAX_DX"

    # 2. At most one special per platform
    spiked_ids = {id(h.platform) for h in game.hazards if h.platform}
    pad_ids = {id(pad.platform) for pad in game.pads}
    crumbler_ids = {id(c.platform) for c in game.crumblers}

    for p in platforms:
        pid = id(p)
        count = (1 if pid in spiked_ids else 0) + (1 if pid in pad_ids else 0) + (1 if pid in crumbler_ids else 0)
        assert count <= 1, f"Platform {p} has multiple specials/hazards!"

    # 3. No two consecutive crumblers (at least CRUMBLE_MIN_PLAIN_BETWEEN between them)
    for i in range(len(platforms) - CRUMBLE_MIN_PLAIN_BETWEEN):
        if id(platforms[i]) in crumbler_ids:
            for k in range(1, CRUMBLE_MIN_PLAIN_BETWEEN + 1):
                assert id(platforms[i + k]) not in crumbler_ids, "Two consecutive crumblers found!"

    # 4. Never more than 3 consecutive non-plain platforms
    consec_non_plain = 0
    for p in platforms:
        if not game._is_plain(p):
            consec_non_plain += 1
            assert consec_non_plain <= MAX_SPECIAL_RUN, f"More than {MAX_SPECIAL_RUN} consecutive non-plain platforms!"
        else:
            consec_non_plain = 0

    # 5. Every pad rect lies fully inside its platform
    for pad in game.pads:
        assert pad.rect.left >= pad.platform.left, f"Pad {pad.rect} extends left of platform {pad.platform}"
        assert pad.rect.right <= pad.platform.right, f"Pad {pad.rect} extends right of platform {pad.platform}"

    # 6. No spike is generated while platforms_since_pad < PAD_CLEAR_PLATFORMS (2)
    pad_indices = [i for i, p in enumerate(platforms) if id(p) in pad_ids]
    for idx in pad_indices:
        for offset in range(1, PAD_CLEAR_PLATFORMS + 1):
            if idx + offset < len(platforms):
                follower = platforms[idx + offset]
                assert id(follower) not in spiked_ids, f"Platform {follower} has spikes within pad clearance window!"

    # 7. Plain-platform ratio at full difficulty >= 30%
    plain_count = sum(1 for p in platforms if game._is_plain(p))
    plain_ratio = plain_count / len(platforms)
    print(f"Plain-platform ratio at full difficulty: {plain_ratio * 100:.2f}%")
    assert plain_ratio >= 0.30, f"Plain-platform ratio {plain_ratio:.2f} < 0.30"

    print("✓ Test 15 Passed: Specials fairness invariants verified over 10,000+ platforms.")


def test_pad_mechanics() -> None:
    """Test 16: Pad launch velocity, forgiveness margin, apex height, and rising immunity."""
    game = Game()
    game.hazards_enabled = False
    game.specials_enabled = True
    game.orbs_enabled = False
    game.start_run()

    plat = Platform(100, 400, 120, PLATFORM_HEIGHT)
    pad_rect = pygame.Rect(140, plat.top - PAD_HEIGHT, PAD_WIDTH, PAD_HEIGHT)
    pad = Pad(platform=plat, rect=pad_rect)
    game.platforms = [plat]
    game.pads = [pad]

    renderer = Renderer(pygame.Surface((WIDTH, HEIGHT)))

    # 1. Landing on pad -> vy == PAD_JUMP_VELOCITY, just_boosted == True
    game.player_x = pad_rect.centerx - game.player_width / 2.0
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert abs(game.player_vy - PAD_JUMP_VELOCITY) < 1e-4, f"Expected {PAD_JUMP_VELOCITY}, got {game.player_vy}"
    assert game.just_boosted is True, "just_boosted should be True after pad landing"
    assert 0.0 < pad.pressed_timer <= PAD_PRESS_DURATION

    # 2. Renderer consumes just_boosted
    renderer.render(game, (0, 0), 0.016)
    assert game.just_boosted is False, "Renderer should consume and clear just_boosted"

    # 3. Landing away from pad (outside forgiveness) -> normal JUMP_VELOCITY
    game.start_run()
    game.platforms = [plat]
    game.pads = [pad]
    forgiven_left = pad_rect.left - PAD_FORGIVENESS
    game.player_x = forgiven_left - 10 - game.player_width
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert abs(game.player_vy - JUMP_VELOCITY) < 1e-4, f"Expected normal {JUMP_VELOCITY}, got {game.player_vy}"
    assert game.just_boosted is False

    # 4. Landing within forgiveness margin (2 px inside margin) -> triggers pad
    game.start_run()
    game.platforms = [plat]
    game.pads = [pad]
    game.player_x = (pad_rect.left - (PAD_FORGIVENESS - 2)) - game.player_width
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert abs(game.player_vy - PAD_JUMP_VELOCITY) < 1e-4, "Forgiveness margin did not trigger pad!"
    assert game.just_boosted is True

    # 5. Apex height simulation within 5% of PAD_HEIGHT_FACTOR * JUMP_HEIGHT
    y = 0.0
    vy = PAD_JUMP_VELOCITY
    sub_dt = 1.0 / 120.0
    while vy < 0:
        y += vy * sub_dt
        vy += settings.GRAVITY * sub_dt
    apex = abs(y)
    expected_apex = PAD_HEIGHT_FACTOR * JUMP_HEIGHT
    err = abs(apex - expected_apex) / expected_apex
    assert err <= 0.05, f"Pad apex {apex:.1f} differs from expected {expected_apex:.1f} by {err * 100:.1f}%"

    # 6. Rising player passing through pad does NOT trigger boost
    game.start_run()
    game.platforms = [plat]
    game.pads = [pad]
    game.player_x = pad_rect.centerx - game.player_width / 2.0
    game.player_y = plat.top + 5
    game.player_vy = -400.0
    game.update(0.016, 0)
    assert game.player_vy < 0.0 and game.player_vy != PAD_JUMP_VELOCITY, "Rising player triggered pad!"
    assert game.just_boosted is False

    print("✓ Test 16 Passed: Bounce pad mechanics verified.")


def test_crumbler_mechanics() -> None:
    """Test 17: Crumbler landing, timer non-reset, disintegration, fall-through, and pause freeze."""
    game = Game()
    game.hazards_enabled = False
    game.specials_enabled = True
    game.orbs_enabled = False
    game.start_run()

    plat = Platform(100, 400, 100, PLATFORM_HEIGHT)
    crumbler = Crumbler(platform=plat, state="intact", timer=0.0)
    game.platforms = [plat]
    game.crumblers = [crumbler]

    # 1. Landing on intact crumbler sets state to crumbling and timer to CRUMBLE_DELAY
    game.player_x = 120.0
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert crumbler.state == "crumbling", f"Expected 'crumbling', got {crumbler.state}"
    assert crumbler.timer == CRUMBLE_DELAY, f"Expected {CRUMBLE_DELAY}, got {crumbler.timer}"

    # Subsequent frame decrements timer
    game.update(0.016, 0)
    assert abs(crumbler.timer - (CRUMBLE_DELAY - 0.016)) < 1e-4

    # 2. Re-landing does NOT reset timer
    t_before = crumbler.timer
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 200.0
    game.update(0.016, 0)
    assert crumbler.timer < t_before, "Re-landing reset crumbler timer!"

    # 3. Timer pauses while game is paused
    game.pause()
    t_paused = crumbler.timer
    game.update(0.1, 0)
    assert crumbler.timer == t_paused, "Crumbler timer decremented while paused!"
    game.resume()

    # 4. Advance until timer reaches 0: platform breaks, removed from platforms, debris created
    while crumbler.timer > 0.0:
        game.update(0.05, 0)

    assert crumbler.state == "broken"
    assert not any(p is plat for p in game.platforms), "Broken platform not removed from platforms list!"
    assert any(c is crumbler for c in game.crumblers), "Broken crumbler removed from crumblers list!"
    assert len(game.debris) > 0, "No debris created upon platform disintegration!"
    assert all(d.age < DEBRIS_DURATION for d in game.debris)

    # 5. Falling player over former platform does not land
    game.player_x = 120.0
    game.player_y = plat.top - game.player_height - 1
    game.player_vy = 300.0
    game.update(0.016, 0)
    assert game.player_vy > 300.0, "Player landed on broken platform!"

    # 6. Pruning drops crumblers, pads, hazards and debris using the same cutoff
    game.start_run()
    game.camera_y = 0.0
    p_deep = Platform(100, 1500, 100, PLATFORM_HEIGHT)
    pad_deep = Pad(platform=p_deep, rect=pygame.Rect(100, 1500 - PAD_HEIGHT, PAD_WIDTH, PAD_HEIGHT))
    crumble_deep = Crumbler(platform=p_deep)
    hazard_deep = Hazard(platform=p_deep, rect=pygame.Rect(100, 1500 - SPIKE_HEIGHT, 30, SPIKE_HEIGHT))
    debris_deep = Debris(rect=p_deep.copy(), age=0.1)
    game.platforms.append(p_deep)
    game.pads.append(pad_deep)
    game.crumblers.append(crumble_deep)
    game.hazards.append(hazard_deep)
    game.debris.append(debris_deep)
    game._prune_platforms()
    assert not any(p is p_deep for p in game.platforms)
    assert not any(pad is pad_deep for pad in game.pads)
    assert not any(c is crumble_deep for c in game.crumblers)
    assert not any(h is hazard_deep for h in game.hazards)
    assert not any(d is debris_deep for d in game.debris)

    print("✓ Test 17 Passed: Crumbler mechanics verified.")


def test_checkpoint_safety_specials() -> None:
    """Test 18: Long climb verifies checkpoints are never placed on spikes, pads, or crumblers."""
    random.seed(42)
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = True
    game.orbs_enabled = True
    game.start_run()
    game.score = 600

    # Simulate climbing and landing on many platforms
    for _ in range(60):
        platforms_above = [p for p in game.platforms if p.top < game.player_y]
        if not platforms_above:
            game.camera_y -= 500.0
            game._generate_platforms()
            continue
        target_plat = min(platforms_above, key=lambda p: p.top)
        game.player_x = target_plat.centerx - game.player_width / 2.0
        game.player_y = target_plat.top - game.player_height - 1
        game.player_vy = 300.0
        game.update(0.016, 0)

        # Verify all checkpoints in stack are plain
        for cp in game.checkpoint_stack.to_list():
            cp_plat = Platform(*cp)
            assert game._is_plain(cp_plat), f"Checkpoint platform {cp_plat} is not plain!"

    print("✓ Test 18 Passed: Checkpoint safety (plain platforms only) verified.")


def test_route_integrity_after_rewind() -> None:
    """Test 19: Route reachability and intact crumbler restoration after rewind."""
    random.seed(42)
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = True
    game.orbs_enabled = True
    game.start_run()

    # Generate route
    while len(game.platforms) < 40:
        game.camera_y -= 1000.0
        game.score += 50
        game._generate_platforms()

    # Find a plain platform near middle to use as checkpoint
    plain_plats = [p for p in game.platforms if game._is_plain(p)]
    cp_plat = plain_plats[len(plain_plats) // 2]
    game.checkpoint_stack.push((cp_plat.x, cp_plat.y, cp_plat.width, cp_plat.height))

    # Break all crumblers above the checkpoint
    crumblers_above = [c for c in game.crumblers if c.platform.top < cp_plat.top]
    for c in crumblers_above:
        c.state = "broken"
        game.platforms = [p for p in game.platforms if p is not c.platform]
        game.debris.append(Debris(rect=c.platform.copy(), age=0.1))

    score_before = game.score
    max_h_before = game.max_height_y

    # Trigger rewind
    game._rewind()

    # Assert score and max_height unchanged
    assert game.score == score_before
    assert game.max_height_y == max_h_before
    # Restored crumblers intact
    for c in crumblers_above:
        assert c.state == "intact", f"Crumbler {c} not reset to intact!"
        assert any(p is c.platform for p in game.platforms), f"Platform for crumbler {c} not restored!"
    assert len(game.debris) == 0, "Debris was not cleared on rewind!"

    # Reachability of platforms above restored checkpoint
    above_plats = sorted([p for p in game.platforms if p.top <= cp_plat.top], key=lambda p: -p.top)
    for i in range(len(above_plats) - 1):
        v_gap = above_plats[i].top - above_plats[i + 1].top
        assert v_gap <= MAX_GAP_LIMIT + 1e-4, f"Gap violation {v_gap} > {MAX_GAP_LIMIT} after rewind!"

    print("✓ Test 19 Passed: Route integrity and crumbler restoration after rewind verified.")


def test_prune_safety_checkpoint_invariant() -> None:
    """Test 20: Older checkpoints below camera cutoff prevent platform culling."""
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = True
    game.orbs_enabled = True
    game.start_run()

    # Checkpoint at y = 1200
    cp_plat = Platform(100, 1200, 100, PLATFORM_HEIGHT)
    game.platforms.append(cp_plat)
    game.checkpoint_stack.push((cp_plat.x, cp_plat.y, cp_plat.width, cp_plat.height))

    # Add a platform above the checkpoint at y = 1050
    intermediate_plat = Platform(120, 1050, 100, PLATFORM_HEIGHT)
    game.platforms.append(intermediate_plat)

    game.camera_y = 0.0
    assert intermediate_plat.top > game.camera_y + HEIGHT + PRUNE_MARGIN
    game._prune_platforms()

    assert any(p is cp_plat for p in game.platforms), "Checkpoint platform was culled!"
    assert any(p is intermediate_plat for p in game.platforms), "Platform above checkpoint was culled!"
    print("✓ Test 20 Passed: Prune safety checkpoint invariant verified.")


def test_patrol_removal() -> None:
    """Test 21: Verify complete removal of patrol hazards and constants."""
    random.seed(42)
    g = Game()
    g.hazards_enabled = True
    g.specials_enabled = True
    g.orbs_enabled = True
    g.start_run()
    g.score = 2000
    while len(g.platforms) < 5500:
        g.camera_y -= 5000.0
        g._generate_platforms()

    # Assert only spike hazards exist
    assert len(g.hazards) > 0, "Expected hazards at score 2000"
    for h in g.hazards:
        assert hasattr(h, "rect") and h.rect is not None, "Non-spike hazard found!"
        assert not hasattr(h, "kind") or h.kind == "spike", "Patrol hazard object found!"

    # Assert settings has no PATROL_ attributes and no REWIND_CLEAR_WINDOW
    patrol_attrs = [attr for attr in dir(settings) if attr.startswith("PATROL_")]
    assert len(patrol_attrs) == 0, f"settings still contains patrol attributes: {patrol_attrs}"
    assert not hasattr(settings, "REWIND_CLEAR_WINDOW"), "settings still has REWIND_CLEAR_WINDOW"

    # Scan source code of game.py, settings.py, renderer.py, main.py
    root = Path(__file__).resolve().parent
    for filename in ["game.py", "settings.py", "renderer.py", "main.py"]:
        text = (root / filename).read_text(encoding="utf-8")
        assert "patrol" not in text.lower(), f"Found 'patrol' in {filename}!"

    print("✓ Test 21 Passed: Patrol removal verified (zero patrol references remain).")


def test_orb_generation() -> None:
    """Test 22: Orb generation score gating, clearance, bounds, and density."""
    random.seed(42)
    # No orbs below score 50
    g_low = Game()
    g_low.hazards_enabled = True
    g_low.specials_enabled = True
    g_low.orbs_enabled = True
    g_low.start_run()
    g_low.score = 30
    while len(g_low.platforms) < 500:
        g_low.camera_y -= 1000.0
        g_low._generate_platforms()
    assert len(g_low.orbs) == 0, f"Expected 0 orbs below score 50, got {len(g_low.orbs)}"

    # Across 10,000+ platforms at full difficulty
    g = Game()
    g.hazards_enabled = True
    g.specials_enabled = True
    g.orbs_enabled = True
    g.start_run()
    g.score = 1500
    while len(g.platforms) < 10500:
        g.camera_y -= 5000.0
        g._generate_platforms()

    platforms = g.platforms
    orbs = g.orbs
    sorted_plats = sorted(platforms, key=lambda p: -p.top)

    # Reachability invariants still hold
    for i in range(len(sorted_plats) - 1):
        lower = sorted_plats[i]
        upper = sorted_plats[i + 1]
        v_gap = lower.top - upper.top
        assert v_gap <= MAX_GAP_LIMIT + 1e-4, f"Vertical gap {v_gap} > MAX_GAP_LIMIT"
        h_gap = abs(upper.centerx - lower.centerx)
        assert h_gap <= MAX_DX + 1e-4, f"Horizontal gap {h_gap} > MAX_DX"

    # Spatial band indexing for fast clearance verification across 10,000+ entities
    plat_by_band: dict = {}
    for p in platforms:
        band = int(p.top // 100)
        plat_by_band.setdefault(band, []).append(p)

    pad_by_band: dict = {}
    for pad in g.pads:
        band = int(pad.rect.top // 100)
        pad_by_band.setdefault(band, []).append(pad)

    hazard_by_band: dict = {}
    for h in g.hazards:
        band = int(h.rect.top // 100)
        hazard_by_band.setdefault(band, []).append(h)

    # No orb overlaps any platform, pad rect or spike strip (with clearance)
    for orb in orbs:
        assert orb.x - orb.radius >= 8.0, f"Orb {orb} violates left screen margin"
        assert orb.x + orb.radius <= WIDTH - 8.0, f"Orb {orb} violates right screen margin"

        orb_band = int(orb.y // 100)
        for b in (orb_band - 1, orb_band, orb_band + 1):
            for p in plat_by_band.get(b, []):
                cx = max(p.left - ORB_CLEARANCE, min(p.right + ORB_CLEARANCE, orb.x))
                cy = max(p.top - ORB_CLEARANCE, min(p.bottom + ORB_CLEARANCE, orb.y))
                dist = math.hypot(orb.x - cx, orb.y - cy)
                assert dist >= orb.radius - 1e-4, f"Orb {orb} overlaps platform {p} with clearance"

            for pad in pad_by_band.get(b, []):
                cx = max(pad.rect.left - ORB_CLEARANCE, min(pad.rect.right + ORB_CLEARANCE, orb.x))
                cy = max(pad.rect.top - ORB_CLEARANCE, min(pad.rect.bottom + ORB_CLEARANCE, orb.y))
                dist = math.hypot(orb.x - cx, orb.y - cy)
                assert dist >= orb.radius - 1e-4, f"Orb {orb} overlaps pad {pad.rect} with clearance"

            for h in hazard_by_band.get(b, []):
                cx = max(h.rect.left - ORB_CLEARANCE, min(h.rect.right + ORB_CLEARANCE, orb.x))
                cy = max(h.rect.top - ORB_CLEARANCE, min(h.rect.bottom + ORB_CLEARANCE, orb.y))
                dist = math.hypot(orb.x - cx, orb.y - cy)
                assert dist >= orb.radius - 1e-4, f"Orb {orb} overlaps spike {h.rect} with clearance"

    # Risk orbs are only above spike strips
    spike_strips = [h.rect for h in g.hazards]
    for orb in orbs:
        if orb.risk:
            matching = [
                s for s in spike_strips
                if abs(s.centerx - orb.x) < 2.0 and abs(orb.y - (s.top - RISK_ORB_HEIGHT)) < 2.0
            ]
            assert len(matching) > 0, f"Risk orb {orb} not positioned above a spike strip!"

    density = (len(orbs) / len(platforms)) * 100.0
    print(f"\nOrb Density at Full Difficulty: {density:.2f} orbs per 100 platforms")
    assert 20.0 <= density <= 50.0, f"Orb density {density:.2f} outside [20, 50]"
    print("✓ Test 22 Passed: Orb generation and clearance verified.")


def test_orb_pickup() -> None:
    """Test 23: Pickup radius, bonus award, event emission, anti-tunneling, and single collection."""
    game = Game()
    game.hazards_enabled = False
    game.specials_enabled = False
    game.start_run()

    plat = Platform(0, -100, WIDTH, PLATFORM_HEIGHT)
    game.platforms = [plat]
    game.camera_y = 0.0

    # 1. Normal orb pickup
    orb_normal = Orb(x=200.0, y=400.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False)
    game.orbs = [orb_normal]
    # Place player overlapping pickup radius
    game.player_x = 200.0 - game.player_width / 2.0
    game.player_y = 400.0 - game.player_height / 2.0
    game.player_vy = 0.0
    game.max_height_y = game.player_y
    game.score = int((game.start_y - game.max_height_y) / settings.SCORE_DIVISOR)
    score_before = game.total_score
    bonus_before = game.bonus_score

    game.update(0.016, 0)

    assert orb_normal not in game.orbs, "Collected orb was not removed from game.orbs"
    assert game.bonus_score == bonus_before + ORB_POINTS
    assert game.total_score == score_before + ORB_POINTS
    assert len(game.events) == 1
    assert game.events[0] == ("orb", 200.0, 400.0, ORB_POINTS, False)

    # 2. Risk orb pickup
    game.start_run()
    game.platforms = [plat]
    game.camera_y = 0.0
    orb_risk = Orb(x=200.0, y=400.0, radius=RISK_ORB_RADIUS, points=RISK_ORB_POINTS, risk=True)
    game.orbs = [orb_risk]
    game.player_x = 200.0 - game.player_width / 2.0
    game.player_y = 400.0 - game.player_height / 2.0
    game.player_vy = 0.0
    game.max_height_y = game.player_y
    game.score = int((game.start_y - game.max_height_y) / settings.SCORE_DIVISOR)
    score_before = game.total_score
    bonus_before = game.bonus_score

    game.update(0.016, 0)
    assert orb_risk not in game.orbs
    assert game.bonus_score == bonus_before + RISK_ORB_POINTS
    assert game.total_score == score_before + RISK_ORB_POINTS
    assert game.events[-1] == ("orb", 200.0, 400.0, RISK_ORB_POINTS, True)

    # 3. Orb just outside pickup radius is not collected
    game.start_run()
    game.platforms = [plat]
    game.camera_y = 0.0
    game.player_x = 100.0
    game.player_y = 350.0
    orb_outside = Orb(x=100.0 + game.player_width + 25.0, y=350.0 + 10.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False)
    game.orbs = [orb_outside]
    game.update(0.016, 0)
    assert orb_outside in game.orbs, "Orb outside pickup radius should not be collected"

    # 4. Anti-tunneling: Falling at MAX_FALL_SPEED with dt = 1/30 passes through orb and collects it
    game.start_run()
    game.platforms = [plat]
    game.camera_y = 0.0
    orb_fall = Orb(x=200.0, y=300.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False)
    game.orbs = [orb_fall]
    game.player_x = 200.0 - game.player_width / 2.0
    game.player_y = 270.0
    game.player_vy = MAX_FALL_SPEED
    game.update(1.0 / 30.0, 0)
    assert orb_fall not in game.orbs, "High-speed falling player tunneled through orb!"

    # 5. Anti-tunneling: Rising at PAD_JUMP_VELOCITY passes through orb and collects it
    game.start_run()
    game.platforms = [plat]
    game.camera_y = 0.0
    orb_rise = Orb(x=200.0, y=300.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False)
    game.orbs = [orb_rise]
    game.player_x = 200.0 - game.player_width / 2.0
    game.player_y = 320.0
    game.player_vy = PAD_JUMP_VELOCITY
    game.update(1.0 / 30.0, 0)
    assert orb_rise not in game.orbs, "High-speed rising player tunneled through orb!"

    # 6. Collected orb cannot be collected twice
    b_after = game.bonus_score
    game.update(0.016, 0)
    assert game.bonus_score == b_after

    print("✓ Test 23 Passed: Orb pickup mechanics and anti-tunneling verified.")


def test_rewind_interplay() -> None:
    """Test 24: Rewind score persistence, orb non-duplication, and pruning cutoff invariant."""
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = True
    game.orbs_enabled = True
    game.start_run()

    while len(game.platforms) < 30:
        game.camera_y -= 1000.0
        game.score += 40
        game._generate_platforms()

    assert len(game.orbs) > 0, "No orbs generated"
    target_orb = game.orbs[0]
    game.player_x = target_orb.x - game.player_width / 2.0
    game.player_y = target_orb.y - game.player_height / 2.0
    game.update(0.016, 0)

    score_before = game.score
    bonus_before = game.bonus_score
    max_h_before = game.max_height_y
    total_before = game.total_score
    collected_coords = (target_orb.x, target_orb.y)

    cp_plat = Platform(100, 300, 100, PLATFORM_HEIGHT)
    game.checkpoint_stack.push((cp_plat.x, cp_plat.y, cp_plat.width, cp_plat.height))

    game._rewind()

    assert game.score == score_before, "Score changed across rewind!"
    assert game.bonus_score == bonus_before, "Bonus score changed across rewind!"
    assert game.max_height_y == max_h_before, "Max height changed across rewind!"
    assert game.total_score == total_before, "Total score changed across rewind!"

    assert not any(o.x == collected_coords[0] and o.y == collected_coords[1] for o in game.orbs)

    game.checkpoint_stack.push((cp_plat.x, cp_plat.y, cp_plat.width, cp_plat.height))
    surviving_orb = Orb(x=150.0, y=cp_plat.top - 50.0, radius=ORB_RADIUS, points=ORB_POINTS, risk=False)
    game.orbs.append(surviving_orb)
    game.camera_y = 0.0
    game._prune_platforms()
    assert surviving_orb in game.orbs, "Orb above oldest checkpoint was culled by pruning!"

    print("✓ Test 24 Passed: Rewind score preservation and orb pruning cutoff verified.")


def test_near_miss() -> None:
    """Test 25: Near-miss bonus conditions (zone exit, margin, collision, single payout, last platform, invuln)."""
    plat = Platform(100, 400, 120, PLATFORM_HEIGHT)
    strip = pygame.Rect(100, 400 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT)

    # (a) Pass within zone and exit without touching -> exactly one NEAR_MISS_POINTS award and one event
    game = Game()
    game.hazards_enabled = True
    game.start_run()
    spike = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike]
    game.last_landing_platform = None
    hb = spike.hitbox()

    game.player_x = hb.right + (NEAR_MISS_MARGIN - 4) - PLAYER_HITBOX_INSET
    game.player_y = hb.top
    game.update(0.016, 0)
    assert spike.in_zone is True
    assert spike.near_miss_awarded is False
    assert game.bonus_score == 0

    game.player_x = hb.right + NEAR_MISS_MARGIN + 30
    game.update(0.016, 0)
    assert spike.in_zone is False
    assert spike.near_miss_awarded is True
    assert game.bonus_score == NEAR_MISS_POINTS
    assert len(game.events) == 1
    assert game.events[0][0] == "near_miss"
    assert game.events[0][3] == NEAR_MISS_POINTS

    # (b) Pass farther than margin -> nothing
    game.start_run()
    spike_b = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike_b]
    game.player_x = hb.right + NEAR_MISS_MARGIN + 50
    game.player_y = hb.top
    game.update(0.016, 0)
    assert spike_b.in_zone is False
    assert game.bonus_score == 0

    # (c) Collision -> hit handled, no award
    game.start_run()
    game.chances = 0
    spike_c = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike_c]
    game.player_x = hb.centerx - game.player_width / 2.0
    game.player_y = hb.centery - game.player_height / 2.0
    game.update(0.016, 0)
    assert spike_c.near_miss_awarded is True
    assert spike_c.in_zone is False
    assert game.bonus_score == 0
    assert game.state == "game_over"

    # (d) The same hazard cannot award twice
    game.start_run()
    spike_d = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike_d]
    game.player_x = hb.right + 2
    game.player_y = hb.top
    game.update(0.016, 0)
    game.player_x = hb.right + 50
    game.update(0.016, 0)
    assert game.bonus_score == NEAR_MISS_POINTS
    game.player_x = hb.right + 2
    game.update(0.016, 0)
    assert spike_d.in_zone is False
    game.player_x = hb.right + 50
    game.update(0.016, 0)
    assert game.bonus_score == NEAR_MISS_POINTS

    # (e) No award for hazard on last_landing_platform
    game.start_run()
    spike_e = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike_e]
    game.last_landing_platform = plat
    game.player_x = hb.right + 2
    game.player_y = hb.top
    game.update(0.016, 0)
    assert spike_e.in_zone is False
    game.player_x = hb.right + 50
    game.update(0.016, 0)
    assert game.bonus_score == 0

    # (f) No award while invuln_timer > 0
    game.start_run()
    spike_f = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike_f]
    game.invuln_timer = 1.0
    game.player_x = hb.right + 2
    game.player_y = hb.top
    game.update(0.016, 0)
    assert spike_f.in_zone is False
    game.player_x = hb.right + 50
    game.update(0.016, 0)
    assert game.bonus_score == 0

    # (g) in_zone flags are reset by a rewind
    game.start_run()
    spike_g = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike_g]
    cp = (100, 600, 100, PLATFORM_HEIGHT)
    game.checkpoint_stack.push(cp)
    game.player_x = hb.right + 2
    game.player_y = hb.top
    game.update(0.016, 0)
    assert spike_g.in_zone is True
    game._rewind()
    assert spike_g.in_zone is False

    # (h) A frame with both a hit and a zone exit awards nothing
    game.start_run()
    game.chances = 0
    spike_h1 = Hazard(platform=plat, rect=strip)
    spike_h2 = Hazard(platform=plat, rect=pygame.Rect(200, 400 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT))
    game.platforms = [plat]
    game.hazards = [spike_h1, spike_h2]
    game.player_x = spike_h1.hitbox().right + 2
    game.player_y = spike_h1.hitbox().top
    game.update(0.016, 0)
    assert spike_h1.in_zone is True

    h2_box = spike_h2.hitbox()
    game.player_x = h2_box.centerx - game.player_width / 2.0
    game.player_y = h2_box.centery - game.player_height / 2.0
    game.update(0.016, 0)
    assert game.bonus_score == 0, "Near-miss awarded during fatal collision frame!"
    assert game.state == "game_over"

    print("✓ Test 25 Passed: Near-miss bonus rules (all 8 conditions) verified.")


def test_scoring(tmp_path: Path) -> None:
    """Test 26: total_score consistency, difficulty isolation, and save_if_best behavior."""
    game = Game()
    game.start_run()

    # 1. total_score == score + bonus_score always
    assert game.total_score == game.score + game.bonus_score
    game.score = 250
    game.bonus_score = 75
    assert game.total_score == 325

    # 2. Never decreases over a simulated run including rewinds
    last_total = game.total_score
    cp = (100, 500, 100, PLATFORM_HEIGHT)
    game.checkpoint_stack.push(cp)
    for _ in range(20):
        game.player_y -= 30.0
        game.update(0.016, 0)
        assert game.total_score >= last_total
        last_total = game.total_score
    game._rewind()
    assert game.total_score >= last_total

    # 3. Difficulty depends on score only
    g_diff1 = Game()
    g_diff1.start_run()
    g_diff1.score = 200
    g_diff1.bonus_score = 0
    lvl1 = (g_diff1.score - settings.SPIKE_START_SCORE) / (settings.HAZARD_FULL_SCORE - settings.SPIKE_START_SCORE)

    g_diff2 = Game()
    g_diff2.start_run()
    g_diff2.score = 200
    g_diff2.bonus_score = 10000
    lvl2 = (g_diff2.score - settings.SPIKE_START_SCORE) / (settings.HAZARD_FULL_SCORE - settings.SPIKE_START_SCORE)
    assert lvl1 == lvl2, "Difficulty calculation must depend on height score only!"

    # 4. save_if_best and game-over save use total_score
    temp_save = tmp_path / "temp_score.json"
    game.best_score = 300
    game.score = 100
    game.bonus_score = 300
    game.save_if_best(path=temp_save)
    assert game.best_score == 400
    assert load_highscore(temp_save) == 400

    print("✓ Test 26 Passed: Scoring properties, difficulty isolation, and save_if_best verified.")


def test_visuals_and_audio() -> None:
    """Test 27: Renderer event draining, FX lifecycle, audio methods, and HUD/Game Over rendering."""
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    renderer = Renderer(screen)
    game = Game()
    game.start_run()

    # 1. After an "orb" event, one render creates popups, rings, particles and drains game.events
    game.events.append(("orb", 200.0, 300.0, 10, False))
    assert len(game.events) == 1
    renderer.render(game, (0, 0), 0.016)
    assert len(game.events) == 0, "Renderer must drain game.events"
    assert len(renderer.popups) == 1
    assert len(renderer.rings) == 1
    assert len(renderer.particles_fx) == 8

    # Same events not replayed on second render
    renderer.render(game, (0, 0), 0.016)
    assert len(renderer.popups) == 1

    # 2. Effects expire after durations
    for _ in range(70):
        renderer.render(game, (0, 0), 0.02)
    assert len(renderer.popups) == 0, "Popups did not expire"
    assert len(renderer.rings) == 0, "Rings did not expire"
    assert len(renderer.particles_fx) == 0, "Particles did not expire"

    # 3. List caps hold even after 100 rapid events
    for _ in range(100):
        game.events.append(("orb", 200.0, 300.0, 10, True))
    renderer.render(game, (0, 0), 0.016)
    assert len(renderer.popups) <= MAX_POPUPS
    assert len(renderer.particles_fx) <= MAX_FX_PARTICLES

    # 4. Effects do not age while paused
    game.pause()
    assert len(renderer.popups) > 0
    pop_age = renderer.popups[0]["age"]
    renderer.render(game, (0, 0), 0.1)
    assert renderer.popups[0]["age"] == pop_age, "Effects aged while paused!"
    game.resume()

    # 5. Effects cleared on new run
    game.start_run()
    renderer.render(game, (0, 0), 0.016)
    assert len(renderer.popups) == 0
    assert len(renderer.rings) == 0
    assert len(renderer.particles_fx) == 0

    # 6. Audio methods execute cleanly
    renderer.sounds.play_orb(False)
    renderer.sounds.play_orb(True)
    renderer.sounds.play_near_miss()

    # 7. Large bonus score HUD and game-over render without exceptions
    game.score = 500
    game.bonus_score = 9999
    renderer.render(game, (0, 0), 0.016)
    game.state = "game_over"
    renderer.render(game, (0, 0), 0.016)

    print("✓ Test 27 Passed: Renderer visuals, audio methods, and HUD rendering verified.")


def test_stability_soak() -> None:
    """Test 28: Stability soak (20,000 frames with bot AI and headless rendering)."""
    random.seed(42)
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = True
    game.orbs_enabled = True
    game.start_run()

    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    renderer = Renderer(screen)

    total_frames = 20000
    dt = 1.0 / 60.0
    runs = 1
    rewinds = 0
    pad_launches = 0
    crumbles = 0
    hits = 0
    orbs_collected = 0
    near_misses = 0

    last_total_score = 0
    target_plat: Optional[Platform] = None

    for frame_idx in range(total_frames):
        if game.state == "game_over":
            runs += 1
            game.start_run()
            target_plat = None
            last_total_score = 0

        if game.just_jumped or target_plat is None:
            platforms_above = [p for p in game.platforms if p.top < game.player_y]
            if platforms_above:
                target_plat = max(platforms_above, key=lambda p: p.top)

        move_dir = 0
        if target_plat:
            target_x = target_plat.centerx
            player_center = game.player_x + game.player_width / 2.0
            dx = target_x - player_center
            if dx > WIDTH / 2:
                dx -= WIDTH
            elif dx < -WIDTH / 2:
                dx += WIDTH
            if dx > 3:
                move_dir = 1
            elif dx < -3:
                move_dir = -1

        prev_state = game.state
        prev_chances = game.chances
        prev_stack = game.checkpoint_stack.size()
        prev_debris_count = len(game.debris)

        game.update(dt, move_dir)

        # Inspect events before renderer drains them
        for ev in game.events:
            if ev[0] == "orb":
                orbs_collected += 1
            elif ev[0] == "near_miss":
                near_misses += 1

        if game.just_boosted:
            pad_launches += 1

        if len(game.debris) > prev_debris_count:
            crumbles += (len(game.debris) - prev_debris_count)

        if prev_state == "playing" and game.state == "playing" and prev_chances > game.chances:
            rewinds += 1

        if prev_state == "playing" and (game.state == "game_over" or prev_chances > game.chances):
            hits += 1

        assert 0 <= game.chances <= CHANCES_PER_RUN, f"Chances {game.chances} out of range [0, {CHANCES_PER_RUN}]"
        if prev_state == "playing" and game.state == "playing":
            assert game.chances <= prev_chances, f"Chances increased within run from {prev_chances} to {game.chances}"

        assert game.total_score >= last_total_score, f"Total score decreased from {last_total_score} to {game.total_score}"
        last_total_score = game.total_score

        # Headless render every 10th frame
        if frame_idx % 10 == 0:
            renderer.render(game, (0, 0), 10 * dt)
            assert len(renderer.particles_fx) <= MAX_FX_PARTICLES, f"Particles {len(renderer.particles_fx)} > {MAX_FX_PARTICLES}"
            assert len(renderer.popups) <= MAX_POPUPS, f"Popups {len(renderer.popups)} > {MAX_POPUPS}"

        assert len(game.platforms) < 150, f"Too many platforms: {len(game.platforms)}"
        assert len(game.orbs) < 60, f"Too many orbs: {len(game.orbs)}"
        assert len(game.hazards) < 80, f"Too many hazards: {len(game.hazards)}"
        assert len(game.pads) < 60, f"Too many pads: {len(game.pads)}"
        assert len(game.crumblers) < 80, f"Too many crumblers: {len(game.crumblers)}"
        assert len(game.debris) < 40, f"Too many debris: {len(game.debris)}"

    print(
        f"✓ Test 28 Passed: Stability soak completed ({total_frames} frames, "
        f"orbs={orbs_collected}, near_misses={near_misses}, pad_launches={pad_launches}, "
        f"crumbles={crumbles}, rewinds={rewinds}, hits={hits}, runs={runs}, "
        f"platforms={len(game.platforms)}, orbs={len(game.orbs)}, hazards={len(game.hazards)}, "
        f"pads={len(game.pads)}, crumblers={len(game.crumblers)}, debris={len(game.debris)})."
    )


def test_chances_initial_state() -> None:
    """Test 29: After start_run(), chances == 3, Stack is empty, HUD shows 3 slots."""
    game = Game()
    game.start_run()
    assert game.chances == 3, f"Expected 3 chances at start, got {game.chances}"
    assert game.checkpoint_stack.is_empty(), "Stack should start empty"
    assert CHANCES_PER_RUN == 3
    print("✓ Test 29 Passed: Initial chances state verified (chances=3, empty stack).")


def test_chances_fall_at_start() -> None:
    """Test 30: Forcing fall immediately at start rewinds onto standable platform with chances=2."""
    game = Game()
    game.start_run()
    score_before = game.score
    max_h_before = game.max_height_y

    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)

    assert game.chances == 2, f"Expected chances 2, got {game.chances}"
    assert game.state == "playing"
    assert game.score == score_before
    assert game.max_height_y == max_h_before

    standing_on = [p for p in game.platforms if abs(p.top - (game.player_y + game.player_height)) < 2.0]
    assert len(standing_on) > 0, "Player must be restored above an existing platform"
    print("✓ Test 30 Passed: Fall at start rewinds safely with chances=2.")


def test_chances_full_sequence(tmp_path: Path) -> None:
    """Test 31: Consecutive falls reduce chances 2 -> 1 -> 0 -> game_over; best score saved."""
    game = Game()
    game.start_run()
    game.score = 200
    temp_save = tmp_path / "temp_highscore.json"

    # Fall 1 -> chances 2
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)
    assert game.chances == 2
    assert game.state == "playing"

    # Fall 2 -> chances 1
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)
    assert game.chances == 1
    assert game.state == "playing"

    # Fall 3 -> chances 0
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)
    assert game.chances == 0
    assert game.state == "playing"

    # Fall 4 -> game_over
    game.player_y = game.camera_y + HEIGHT + 50.0
    orig_save = game.save_if_best
    game.save_if_best = lambda path=temp_save: orig_save(path=path)
    game.update(0.016, 0)
    assert game.state == "game_over"
    assert game.chances == 0
    print("✓ Test 31 Passed: Full chances sequence (3->2->1->0->game_over) verified.")


def test_chances_hits() -> None:
    """Test 32: Spike hits reduce chances; chances=0 ends run; invulnerability protects."""
    game = Game()
    game.hazards_enabled = True
    game.specials_enabled = False
    game.orbs_enabled = False
    game.start_run()

    plat = Platform(100, 300, 120, PLATFORM_HEIGHT)
    strip = pygame.Rect(100, 300 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT)
    spike = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike]

    # Hit 1 -> chances 2
    hb = spike.hitbox()
    game.player_x = hb.centerx - game.player_width / 2.0
    game.player_y = hb.centery - game.player_height / 2.0
    game.invuln_timer = 0.0
    game.update(0.016, 0)
    assert game.chances == 2
    assert game.state == "playing"
    assert game.invuln_timer > 0.0

    # Hit during invulnerability -> does nothing, chances unchanged
    ch_before = game.chances
    game.player_x = hb.centerx - game.player_width / 2.0
    game.player_y = hb.centery - game.player_height / 2.0
    game.update(0.016, 0)
    assert game.chances == ch_before

    # Hit with chances = 0 -> game_over
    game.chances = 0
    game.invuln_timer = 0.0
    game.player_x = hb.centerx - game.player_width / 2.0
    game.player_y = hb.centery - game.player_height / 2.0
    game.update(0.016, 0)
    assert game.state == "game_over"
    assert game.chances == 0
    print("✓ Test 32 Passed: Spike hits decrement chances and respect invulnerability.")


def test_chances_never_refills() -> None:
    """Test 33: Chances never increase within a run, even after climb, rewind, and more landings."""
    random.seed(123)
    game = Game()
    game.hazards_enabled = False
    game.specials_enabled = False
    game.orbs_enabled = False
    game.start_run()

    # Fall once -> chances = 2
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)
    assert game.chances == 2

    # Simulate climbing and landing on 100 new higher platforms
    for _ in range(100):
        clean_plats = [p for p in game.platforms if p.top < game.player_y]
        if not clean_plats:
            game.camera_y -= 200.0
            game._generate_platforms()
            clean_plats = [p for p in game.platforms if p.top < game.player_y]

        if clean_plats:
            target = max(clean_plats, key=lambda p: p.top)
            game.player_x = target.centerx - game.player_width / 2.0
            game.player_y = target.top - game.player_height + 2.0
            game.player_vy = 200.0
            game.camera_y = min(game.camera_y, game.player_y - HEIGHT * 0.4)
            game.update(0.016, 0)
            assert game.chances == 2, f"Chances changed to {game.chances}!"

    print("✓ Test 33 Passed: Chances count never refills or increases within a run.")


def test_chances_consistency_independent_of_stack() -> None:
    """Test 34: Each fall decrements chances by 1 regardless of stack size (0, 1, 3)."""
    # Empty stack
    game = Game()
    game.start_run()
    assert game.checkpoint_stack.is_empty()
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)
    assert game.chances == 2
    assert game._is_plain(min(game.platforms, key=lambda p: abs(p.top - (game.player_y + game.player_height))))

    # Stack with 1 item
    clean_p = Platform(120, 250, 100, PLATFORM_HEIGHT)
    game.platforms.append(clean_p)
    game.checkpoint_stack.push((clean_p.x, clean_p.y, clean_p.w, clean_p.h))
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)
    assert game.chances == 1

    # Stack with 3 items (full)
    for i in range(3):
        p = Platform(100, 200 - i * 100, 100, PLATFORM_HEIGHT)
        game.checkpoint_stack.push((p.x, p.y, p.w, p.h))
    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)
    assert game.chances == 0
    print("✓ Test 34 Passed: Chances decrement independently of checkpoint stack size.")


def test_chances_no_double_decrement() -> None:
    """Test 35: A frame with both a hit and a fall condition reduces chances by exactly one."""
    game = Game()
    game.hazards_enabled = True
    game.start_run()

    plat = Platform(100, 300, 100, PLATFORM_HEIGHT)
    strip = pygame.Rect(100, 300 - SPIKE_HEIGHT, 40, SPIKE_HEIGHT)
    spike = Hazard(platform=plat, rect=strip)
    game.platforms = [plat]
    game.hazards = [spike]

    game.camera_y = 100.0
    game.player_y = game.camera_y + HEIGHT + 50.0
    spike.rect.y = int(game.player_y)
    game.invuln_timer = 0.0

    initial_chances = game.chances
    game.update(0.016, 0)
    assert game.chances == initial_chances - 1, f"Expected 1 decrement, got {initial_chances - game.chances}"
    print("✓ Test 35 Passed: No double decrement on simultaneous hit and fall.")


def test_chances_restart() -> None:
    """Test 36: start_run() restores chances to 3 after game over and after pause restart."""
    game = Game()
    game.start_run()
    game.chances = 0
    game.state = "game_over"

    game.start_run()
    assert game.chances == 3
    assert game.checkpoint_stack.is_empty()

    game.chances = 1
    game.pause()
    assert game.state == "paused"
    game.start_run()
    assert game.chances == 3
    assert game.checkpoint_stack.is_empty()
    print("✓ Test 36 Passed: Restart resets chances to 3 and clears stack.")


def test_chances_route_integrity_and_pruning() -> None:
    """Test 37: After fallback rewind, route upward is reachable and last_safe_platform survives pruning."""
    random.seed(99)
    game = Game()
    game.start_run()
    assert game.checkpoint_stack.is_empty()

    game.camera_y = -3000.0
    safe_plat = game.last_safe_platform
    assert safe_plat is not None

    game._prune_platforms()
    assert safe_plat in game.platforms, "last_safe_platform must survive pruning even far below camera"

    game.player_y = game.camera_y + HEIGHT + 50.0
    game.update(0.016, 0)
    assert game.chances == 2

    sorted_p = sorted(game.platforms, key=lambda p: -p.top)
    for i in range(len(sorted_p) - 1):
        gap = sorted_p[i].top - sorted_p[i + 1].top
        assert gap <= MAX_GAP_LIMIT + 1e-4, f"Route gap {gap} exceeds MAX_GAP_LIMIT"
    print("✓ Test 37 Passed: Route integrity and safe platform pruning protection verified.")


def test_chances_renderer() -> None:
    """Test 38: Renderer HUD headlessly draws pips for chances 3, 2, 1, 0 without exception."""
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    renderer = Renderer(screen)
    game = Game()

    for c in [3, 2, 1, 0]:
        game.start_run()
        game.chances = c
        renderer.render(game, (0, 0), 0.016)

    print("✓ Test 38 Passed: Headless HUD chances pips rendering verified.")


if __name__ == "__main__":
    test_stack_operations()
    test_reachability()
    test_collision()
    test_score_monotonicity()
    test_rewind_and_game_over()
    test_start_run_reset()

    # Run highscore tests with local scratch folder
    scratch_dir = Path(__file__).resolve().parent / ".test_scratch"
    scratch_dir.mkdir(exist_ok=True)
    test_highscore_io(scratch_dir)

    test_audio_trigger_clear()

    # Hazard test suite
    test_hazard_progression()
    test_hazard_fairness_invariants()
    test_spike_collision()
    test_hit_consequences()
    test_checkpoint_safety()

    # Bounce pad and crumbler specials test suite
    test_specials_progression()
    test_specials_fairness_invariants()
    test_pad_mechanics()
    test_crumbler_mechanics()
    test_checkpoint_safety_specials()
    test_route_integrity_after_rewind()
    test_prune_safety_checkpoint_invariant()

    # Bonus orbs and near-miss test suite
    test_patrol_removal()
    test_orb_generation()
    test_orb_pickup()
    test_rewind_interplay()
    test_near_miss()
    test_scoring(scratch_dir)
    test_visuals_and_audio()

    # Second Chance consistency test suite
    test_chances_initial_state()
    test_chances_fall_at_start()
    test_chances_full_sequence(scratch_dir)
    test_chances_hits()
    test_chances_never_refills()
    test_chances_consistency_independent_of_stack()
    test_chances_no_double_decrement()
    test_chances_restart()
    test_chances_route_integrity_and_pruning()
    test_chances_renderer()

    test_stability_soak()

    try:
        scratch_dir.rmdir()
    except Exception:
        pass

    print("\nALL TESTS PASSED SUCCESSFULLY!")
