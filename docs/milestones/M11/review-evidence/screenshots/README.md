# M11 synthetic browser captures

These seven captures were produced by `scripts/m11_browser_acceptance.py` from
`tests/fixtures/m11/human_scenes.rpy` plus generated synthetic appendix labels. They contain no
private-corpus source, dialogue, images, or assets.

- The scene overview shows the common story spine, the separate persistent-lane presentation for
  the M10-classified terminal route split, chapter navigation, and temporary-choice counts.
- `m11-scenes-cards-200.png` is the same 200% synthetic scene view scrolled to the graph. It keeps
  the story-spine label and all three lane cards visible; the original 200% overview is retained to
  document the responsive header, chapter hierarchy, and route legend.
- The detail view shows a temporary container whose first arm has three arm-local scenes, plus its
  exact qualified provenance and source locators.
- The canonical view shows the direct escape from scene detail to M10 control-flow authority.
- Each view was captured at both 100% and 200%. Browser acceptance reported no overflow, provider
  construction, or remote request at either zoom.

| Capture | SHA-256 |
| --- | --- |
| `m11-scenes-100.png` | `B2544909B1A6D265B9786BB9C06F515E1C699BC741DFCF85434E1EC367F4A914` |
| `m11-scene-detail-100.png` | `928B67386928FCA6AD444F48FC79741A3DC4D48AE3CABDC844A3C1C29949EB53` |
| `m11-canonical-escape-100.png` | `950A7EC303F3C8DBB651962BCB5476038D75754AFCB9D054FDEBEEE847162F68` |
| `m11-scenes-200.png` | `C4EF92D29F15ED6E1ABF6C9A58A8474BCDECB3BBA5999AD4215921BA21B72D37` |
| `m11-scenes-cards-200.png` | `8C44C9FDEB3B109900C6657F6E45757FAF61602A2841DBC2E5101138E2FC5AF4` |
| `m11-scene-detail-200.png` | `8D7B018BF43EB9D80D5A3C5448679A54C3F7D07F49519DB0224A9FA8EDC81867` |
| `m11-canonical-escape-200.png` | `FAAA42D43764103D00BB7A48B139CE133C1AF2930930D1D0CE2C41DDE95D1882` |
