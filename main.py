"""Main entry point and game loop for One More Jump.

Initializes Pygame, handles keyboard and mouse input events, advances
simulation state, and renders the visual presentation at 60 FPS.
"""

import sys
import pygame

from game import Game
from renderer import BUTTONS, Renderer
from settings import FPS, HEIGHT, TITLE, WIDTH


def main() -> None:
    """Initialize system resources and execute the core application loop."""
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption(TITLE)
    clock = pygame.time.Clock()

    game, renderer = Game(), Renderer(screen)
    running = True

    while running:
        dt = clock.tick(FPS) / 1000.0
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.save_if_best()
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_p) and game.state in ("playing", "paused"):
                    game.toggle_pause()
                elif event.key == pygame.K_ESCAPE:
                    if game.state == "menu":
                        game.save_if_best()
                        running = False
                    elif game.state == "game_over":
                        game.state = "menu"
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if game.state in ("menu", "game_over"):
                        game.start_run()
                    elif game.state == "paused":
                        game.resume()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if game.state in ("menu", "game_over") and BUTTONS["play"].collidepoint(mouse_pos):
                    game.start_run()
                elif game.state == "playing" and BUTTONS["pause"].collidepoint(mouse_pos):
                    game.pause()
                elif game.state == "paused":
                    if BUTTONS["resume"].collidepoint(mouse_pos):
                        game.resume()
                    elif BUTTONS["restart"].collidepoint(mouse_pos):
                        game.start_run()
                    elif BUTTONS["menu"].collidepoint(mouse_pos):
                        game.state = "menu"
                elif game.state == "game_over" and BUTTONS["go_menu"].collidepoint(mouse_pos):
                    game.state = "menu"

        move_dir = 0
        if game.state == "playing":
            keys = pygame.key.get_pressed()
            move_dir = (1 if keys[pygame.K_RIGHT] or keys[pygame.K_d] else 0) - (1 if keys[pygame.K_LEFT] or keys[pygame.K_a] else 0)
            game.update(dt, move_dir)

        # Draw frame
        renderer.render(game, mouse_pos, dt)
        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
