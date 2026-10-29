# Family AI Game Day

Pick a game, play together, and let the local AI referee review a video clip and update the score.

## Start the game

You only need to set this up once on your Windows computer:

1. Install **Python 3.10 or newer**.
2. Open PowerShell in this project folder.
3. Install the app's packages:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Start the app:

   ```powershell
   python run.py
   ```

5. Open **http://localhost:8000** in your browser.

Keep the PowerShell window open while you play. To stop the app, press **Ctrl+C** in that window. If Windows says port 8000 is already in use, close the other running copy of the app first.

## Play a round

1. Pick one of the five games and add the players.
2. Read the rules and press **Everyone ready**.
3. On the play screen, either record with your camera and microphone or choose a saved video.
4. Press **Judge this round**. For Football and Bucket Toss, mark the goals or bucket on the first frame and tap the players or ball when asked.
5. Review the AI's notes and annotated video, then press **Apply AI results** to update the score.

For best Football results, use a steady side view with the whole play area in frame, two players who look different from each other, and a visible ball. Short, clear clips are easiest to test.

## What to expect the first time

The app downloads its AI models the first time a game needs them. Keep the computer online and allow a few minutes for that first run. FFmpeg is included through the Python packages, so you normally do not need to install it separately.

Camera recording works on `localhost` in modern browsers. You can also use a video saved on your computer. MP4 and WebM are recommended.

## The games

- **Football** — detects people and the ball, estimates possession, and checks marked goal areas.
- **Majlis Freeze** — compares player movement after the music stops.
- **Say It Right** — listens to an Arabic or English answer to a UAE heritage question.
- **Hand Duel** — recognizes Falcon, Dhow, and Dallah hand signs.
- **Bean-Bag Bucket Toss** — tracks a bright bean bag around the marked bucket.

This is a school-project prototype. Camera angle, lighting, distance, and how clearly objects appear can affect the AI's decisions. Review the clip and events before applying a score.

## Keep your project safe

The app stores temporary uploads and annotated clips in `uploads` and `outputs`. These folders are excluded from source control. The local signing key is in `.env`; do not share that file. `.env.example` is only a template.

## Optional: run a judge from PowerShell

The web app is easiest for normal play. If you have a judge config JSON already prepared, you can run a clip directly:

```powershell
python standalone_judge.py clip.mp4 --game football --config config.json --out report.json
python standalone_judge.py --verify report.json
```
