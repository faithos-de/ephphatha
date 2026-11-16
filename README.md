# Ephphatha

> *Ephphatha*, "be opened": the word Jesus spoke to a man who could neither hear nor speak, and his ears were
> opened and his tongue was released, and he spoke plainly (Mark 7:34–35).

Listen to recorded lines one by one in the browser and say what must be spoken again. Each line shows the text before
and after with a word diff, both recordings and the takes to choose from; mark it as fine, *record again* or *change
text*, add a note, and hand the list back to whoever renders the voices. Made for the TTS voices of the game
[*Augenzeuge*](https://augenzeuge.faithos.de) (FaithOS), but it knows nothing about the game: any list of lines with
audio files works. MIT licensed (see `LICENSE`).

- One Python file, standard library only, plus one HTML page without dependencies.
- Works on a phone in the same Wi-Fi (`--lan`); audio is served with byte ranges, as iPhone Safari requires.
- Every request needs a token (a new random one each start). The server writes exactly one file, the verdicts next to
  the manifest, and serves audio only from the manifest's media folder.
- Verdicts are saved shortly after each change; if the server cannot be reached they are kept in the browser and sent later.

## Use

```bash
python3 tools/ephphatha/ephphatha.py path/to/review.json          # http://127.0.0.1:8790/?t=…
python3 tools/ephphatha/ephphatha.py path/to/review.json --lan    # open the printed link on the phone
python3 tools/ephphatha/ephphatha.py path/to/review.json --todo   # what the reviewer did not accept, as JSON
```

Keys: `J`/`K` next/previous, `Space` play the new recording, `V` play the old one, `T` next take, `1` fine,
`2` record again, `3` change text, `N` note, `Esc` leave the note.

## Manifest (`review.json`)

```json
{
  "title": "Bibeltexte nach Rösch",
  "lang": "de",
  "media": "audio",
  "items": [
    {
      "id": "a1b2c3d4",
      "group": "Akt II",
      "ref": "Joh 6,35",
      "where": "js/akt2.js:412",
      "speaker": "Jesus",
      "before": { "text": "…", "audio": "old/a1b2c3d4.mp3" },
      "after":  { "text": "…", "audio": "new/e5f6a7b8.mp3", "takes": [ { "label": "Fassung 2", "audio": "new/e5f6a7b8-2.mp3" } ] },
      "note": "Why the text changed, shown under the item"
    }
  ]
}
```

`media` is relative to the manifest (or absolute); `audio` paths are relative to `media`. `before` or its audio may be
missing (a new line). `lang` is `de` or `en`.

## Verdicts (`review.verdict.json`)

```json
{ "items": { "a1b2c3d4": { "status": "redo", "note": "slower, a pause after 'Leben'", "take": 1, "at": "…" } } }
```

`status` is `ok`, `redo` (record again) or `text` (change the text); `take` is the index of the chosen take (0 = the
first recording, only stored when another one was chosen).
