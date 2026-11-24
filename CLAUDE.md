# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Xiangqi (Cờ tướng / Chinese chess) desktop GUI written in Python + Tkinter ("Yago Lite Pro"), playing against the Pikafish engine. The whole app is the single file `cotuong.py`; there are no third-party Python dependencies (no Pillow). UI strings and code comments are in Vietnamese — keep new ones consistent.

`engine.exe` (Pikafish, Windows binary) and `pikafish.nnue` (its network weights) must sit next to `cotuong.py`: the engine is launched with `cwd` set to the script's directory so it finds the `.nnue` file there.

`QUY_TRINH_PHAT_TRIEN_PHAN_MEM.md` is a standalone software-process document (Scrumban, roles, release rules) and is not documentation for this code.

## Commands

```bash
python cotuong.py                     # run the GUI (needs engine.exe + pikafish.nnue)
python -m unittest test_cotuong       # run all tests
python -m unittest test_cotuong.XiangqiRulesTests.test_horse_leg_can_be_blocked   # single test
```

Tests import only module-level code, so they need no display and run on non-Windows systems (`winsound` is imported optionally for this reason). They cover the rules, the UCI helpers, the opening styles, the sprite and sound generators, and the engine restart limit. `EngineProtocolTests` launch the real `engine.exe` to check the UCI behaviour the GUI relies on: `position ... moves`, and `go ponder` / `ponderhit` / `stop`. They are skipped when the engine is absent or not on Windows. GUI flows are not unit-tested. To check one, drive a real `YagoLiteGUI` from a script (call `root.update()` in a loop, call `apply_move` / `trigger_engine`, and assert on state).

## Architecture

`cotuong.py` is laid out top to bottom as:

1. **`XiangqiRules`** — pure, stateless rules (static/class methods over a board).
   - `piece_can_move` checks movement geometry only. `is_legal_move` also rejects moves that leave one's own king in check, including flying generals.
   - `game_result` returns `(reason, winner)` when the side to move has no legal moves. Both checkmate **and stalemate count as a loss** for the side to move (Xiangqi rule), which a test enforces.
   - `rule60_result(halfmove_clock)` handles the 60-move rule (`RULE60_PLIES = 120`). A draw is reported as `winner = None`.
   - At the user's request there is deliberately **no** repetition adjudication: neither a draw by repetition nor a loss for perpetual check.
2. **UCI and opening helpers** (pure):
   - Search: `SEARCH_LIMITS` / `build_go_command` (time per move, or depth with a time cap).
   - Output parsing and display: `parse_uci_info`, `format_score` (cp and mate, from Red's point of view), `eval_fraction`.
   - Setup and robustness: `recommended_hash_mb` (Hash sized from physical RAM), `engine_restart_allowed`.
   - The opening-style helpers described below.
3. **Graphics and sound helpers** (pure): `SpriteBuffer`, the `render_*_png` functions, `encode_png_rgba`, and `synth_sound` / `ensure_sound_files`.
4. **`OPENING_BOOK`** — dict keyed by the exact FEN string produced by `generate_fen()` → list of UCI moves.
   - Keys must match that format; it always ends in ` - - 0 1`.
   - A test verifies every book move is legal, and at runtime book moves are re-filtered through `XiangqiRules` before a random one is picked.
   - The book is off by default because a random pick from it is weaker than Pikafish's own choice.
5. **Option widgets** — `SegmentedControl`, `ToggleSwitch`, `OptionList`, `Tooltip` (see "Control panel").
6. **`YagoLiteGUI`** — Tkinter UI, game state, undo stack, animation, and engine I/O.

### Board and coordinate conventions

- `board` is a 10×9 list of lists of single chars; `'.'` is empty. Uppercase = Red (`'w'`, bottom, rows 7–9 palace), lowercase = Black (`'b'`, top, rows 0–2 palace). Letters: K/A/B/N/R/C/P (king, advisor, elephant, horse, rook, cannon, pawn).
- Positions are `(row, col)` with row 0 at Black's back rank.
- UCI move strings (engine + book) use file `a`–`i` = col 0–8 and rank `0`–`9` = `9 - row`. Convert with `move_to_text` / `parse_move` (the test file has its own copy of `parse_move`).
- Canvas geometry: 60 px per grid step with a 30 px margin, multiplied by `board_scale` (the board resizes with the window). `is_flipped` mirrors both axes. See `board_to_canvas` and `on_click`.

### Rendering, effects and sound

- Tk on Windows does not antialias canvas shapes, so everything rounded is rasterised in pure Python: pieces, glows, rings, dots, panels and the option widgets. `SpriteBuffer` evaluates a per-pixel shader with distance-based coverage, and `encode_png_rgba` turns the result into a PNG that `tk.PhotoImage` displays with real alpha.
  - Piece glyphs are Tk text drawn over the sprite.
  - `YagoLiteGUI.sprite()` caches PhotoImages by key, with sizes quantised to 0.5 px so small resizes reuse sprites.
  - Window resizes are debounced in `on_board_area_resize`.
- Canvas layers are tags. Anything new drawn on the board must carry one of them.
  - `static`: wood, grain, grid. Redrawn only when the scale or flip changes.
  - `dyn`: markers, pieces, the result banner. Redrawn by every `draw_board`.
  - `hover`.
  - `moving`: the piece in flight, plus the captured piece shown until impact.
  - `fx`: particles, ripples, toasts, confetti.
  - `draw_board` never deletes `moving` / `fx` and raises them to the top.
- Effects run through `add_effect(step)`: one ~60 FPS `after` loop calls each `step(now)` and drops it when it returns False.
  - Effects must not touch the game-state flags, so they never block input. Only `animate_piece` sets `is_animating`.
  - `clear_effects` (run on every new game) kills all of them.
  - The "Hiệu ứng động" switch (`animation_var`) gates move animation, particles, ripples, the check pulse, confetti and the widget slide tweens.
- Game end shows an in-board banner (`result_title` / `result_reason`, dismissed by clicking the board) instead of a messagebox.
- Sounds are synthesised (`synth_sound`: modal "wood knock" and FM bells) and played with `winsound.PlaySound(..., SND_ASYNC)`.
  - A background thread writes them once at startup as WAVs to `%TEMP%/yago_lite_sounds_v<SOUND_VERSION>`.
  - Bump `SOUND_VERSION` after changing a recipe, otherwise the cached files keep being used.

### Control panel

- The right panel (`control_frame`, fixed 370 px) holds:
  - the header, with the collapse button;
  - the engine card: score, depth, eval bar, opening names;
  - the action buttons;
  - a `SegmentedControl` tab bar with three tabs, built by `build_moves_tab` / `build_engine_tab` / `build_game_tab` and switched by `show_tab` (pack / pack_forget);
  - a status bar placed at the bottom with `place()`.
- The tab contents must still fit at the minimum window size of 980×720; the "Máy chơi" tab is the tallest.
- The option widgets redraw through `trace_add` on their Tk variable, so setting a variable from code updates the UI.
  - `SegmentedControl` lights no segment when the variable's value isn't one of its options. This is how the time row and the depth row share `limit_var`.
  - `ToggleSwitch` binds a BooleanVar.
  - `OptionList` shows radio rows for `mode_var`.
  - Their tweens use their own `after` jobs, not `add_effect`, so `clear_effects` can't freeze them.
- `opening_style_var` is the only option value the engine code reads; its values are in `OPENING_STYLE_CHOICES`.
  - The opening segmented control writes it through `select_opening_mode`, and the name combobox `cb_named` writes it as `NAMED_OPENING_PREFIX + name`.
  - `sync_opening_controls`, a trace on `opening_style_var`, mirrors it back into `opening_mode_var` / `named_opening_var` and the hint text.
- Picking a board setup (`select_board_mode`) rebuilds the board immediately only if no move has been played. Otherwise it applies on the next "Ván mới".
- Collapsing the panel ("»" in the header, or Ctrl+B → `toggle_panel` / `set_panel_collapsed`) swaps `control_frame` for `rail`.
  - `rail` is a 58 px strip built by `build_rail`: icon buttons with `Tooltip`s, the score, a vertical eval bar (`draw_rail_eval_bar`) and a status dot.
  - When collapsed, the window minimum drops to 640×720. Expanding widens the window back to 980 px if needed.
  - Because the rail mirrors the panel:
    - change the go button only through `set_go_button`, never `btn_go.config`;
    - change the score only through `set_eval_label`, never `lbl_eval.config`;
    - `set_status` / `pulse_status_dot` also colour `rail_dot`.

### Engine integration (UCI over subprocess)

- `init_engine` spawns `engine.exe`, sends `uci`, `Threads` (CPU count − 2), `Hash` (`recommended_hash_mb()`), `Ponder`, `MultiPV 1` and `isready`, then starts a daemon thread running `listen_engine_loop`.
  - `engine_ready` becomes true only on `readyok`, and `trigger_engine` refuses to search before that.
- The listener thread must never touch Tk, not even `root.after`, which fails before or outside `mainloop`.
  - It calls `post_to_ui`, which pushes `(callback, args)` onto `ui_queue`.
  - `poll_ui_queue` drains that queue on the Tk thread every 15 ms.
- Searches send the **whole game**: `position fen <start_fen> moves <move_list...>` (see `position_command`), so the engine sees repetitions and the 60-move counter.
  - `start_fen` is captured by `reset_game_history()` after handicap pieces are removed in `new_game`.
  - Every move returned by the engine or book is re-validated with `XiangqiRules.is_legal_move` before being applied.
- `setoption` (e.g. `set_multipv`) may only be sent while the engine is idle, i.e. between a `bestmove` and the next `go`.
- **Crash recovery.** This Pikafish build occasionally crashes (0xC0000005, about 1 in 20–40 searches) during the large MultiPV + `searchmoves` search used by Lạ / Rất lạ. It is reproducible with `engine.exe` alone.
  - `on_engine_exit` restarts an engine that had reached `readyok`, via `init_engine(restarting=True)`.
  - If a search was interrupted, the board stays locked with `active_search_source = 'restart'`, and `on_engine_ready` re-runs `trigger_engine`. Undo or new game during the restart (`cancel_pending_action`) drops that retry.
  - `engine_restart_allowed` caps restarts at `ENGINE_RESTART_LIMIT` per `ENGINE_RESTART_WINDOW` seconds.
  - An engine that dies during startup, or that crashes more often than the cap allows, gets the error dialog with its last output lines.
  - The listener passes its `process` to `on_engine_exit` so that a late exit notice from a replaced engine is ignored.

### Opening styles ("Phong cách khai cuộc")

`search_mode_for_ply(ply)` decides how each engine search runs. The result is stored in `search_mode` and read in `handle_engine_bestmove`:

- **Chuẩn** → `normal`: a plain search, the strongest play.
- **Đa dạng** → `varied`, for the first `VARIETY_PLIES` plies: MultiPV 3, then a random pick within `VARIETY_THRESHOLD_CP` (`choose_varied_move`).
- **Lạ / Rất lạ** → `style`, only for each side's first move (ply 0 and 1).
  - The engine scores every legal move in `OPENING_CATALOGUE` at once: `go movetime ... searchmoves <catalogue>`, with MultiPV set to the number of candidates (see `build_opening_go_command`).
  - `choose_style_move` then picks a random non-mainstream move (not in `MAINSTREAM_OPENINGS`) that loses at most `ODD_MAX_LOSS_CP`. For Rất lạ it prefers losses between `ODD_MAX_LOSS_CP` and `VERY_ODD_MAX_LOSS_CP`.
  - If no unusual move is safe enough, it falls back to the engine's best move.
  - The loss is measured by the engine, so odd moves that are blunders in the current position are filtered out automatically. For example, as Black against a central cannon, most odd replies lose 2–4 pawns and are rejected.
- **Theo tên** (`"• <tên>"`) → `named`, only for each side's first move. The names are `NAMED_OPENINGS`: every catalogue name plus Thuận/Nghịch pháo.
  - `named_opening_candidates` returns the legal moves that produce that opening, usually the left/right mirrors.
  - The search is the normal `go` with `searchmoves <candidates>`, so the engine picks the better mirror.
  - There is no loss threshold, because the user chose the opening explicitly.
  - If the opening is impossible in the position, the engine plays normally and the status bar says so.
- `OPENING_CATALOGUE` is written from Red's point of view; Black's moves are looked up through `flip_move_rank`.
- `opening_name` names the first move of each side, including Thuận/Nghịch pháo. The engine card (`update_opening_label`) shows both names, and a toast appears when the engine plays an unusual or named opening.
- The `style`, `named` and `varied` searches can't be pondered, because they need MultiPV or `searchmoves`. Pondering is skipped when the next engine ply would use one of them.
- The opening book is bypassed while `style` or `named` applies.

### Turn / search state machine

Interaction is gated by several flags that must stay consistent when changing flow:

- `is_engine_thinking` — a book lookup, an engine search, or an engine restart with a pending retry is in progress for the side to move.
- `active_search_source` — `'book'`, `'engine'`, `'restart'`, `'animation'` or `None`. Stale callbacks check this and bail out.
- `is_pondering` / `ponder_moves` — after the engine moves, `start_ponder` runs `go ponder` on the engine's predicted reply while the human thinks.
  - `is_engine_thinking` stays false during pondering, so clicks work.
  - If the human's move makes `move_list == ponder_moves`, `trigger_engine` sends `ponderhit`. Otherwise `stop_pondering` sends `stop`.
- `engine_stopping` / `search_cancelled` — set after sending `stop` (cancel or ponder miss).
  - The next `bestmove` is *drained* (discarded) in `on_cancelled_search_drained`.
  - A new search requested meanwhile sets `search_after_drain`, and the search starts once draining completes.
  - This relies on the engine emitting exactly one `bestmove` per `go`.
- `is_animating`, `game_over` — block clicks and new searches.

`cancel_pending_action` is the single entry point for aborting work; undo, new game and close all use it. It:
- cancels the animation, any pending book `after` job, and an engine search or ponder;
- clears `search_after_drain` and any restart retry.

Every move (human, book, or engine) goes through `apply_move`:
- It pushes a snapshot onto `state_stack` for undo: board, turn, last move, game-over/winner, captured pieces, `move_list`, `halfmove_clock`.
- It appends to the move list, flips `turn`, and then animates.
- When the animation finishes, it runs game-result detection (`current_game_result`: the no-legal-moves result, then the 60-move rule), the sounds, and the "after move" callback.
