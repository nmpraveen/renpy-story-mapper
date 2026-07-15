# M11 synthetic browser captures

These eight captures were produced by `scripts/m11_browser_acceptance.py` from
`tests/fixtures/m11/human_scenes.rpy` plus generated synthetic appendix labels. They contain no
private-corpus source, dialogue, images, or assets.

- The scene overview shows the common story spine, the separate persistent-lane presentation for
  the M10-classified terminal route split, chapter navigation, and temporary-choice counts.
- `m11-scenes-cards-100.png` and `m11-scenes-cards-200.png` center the exact M10 terminal split,
  the common-spine source, both persistent-lane entries, and their ordinary scene-flow edges. The
  overview captures retain the responsive header, chapter hierarchy, and route legend.
- The detail view shows a temporary container with three scenes in one arm and one scene in its
  sibling arm, plus exact qualified provenance and source locators.
- The canonical view shows the direct escape from scene detail to M10 control-flow authority.
- Each view was captured at both 100% and 200%. Browser acceptance reported no overflow, provider
  construction, or remote request at either zoom.

| Capture | SHA-256 |
| --- | --- |
| `m11-scenes-100.png` | `7E2404AC4205D965CB11DD1F7D1E022DCC8D74EAD2ED2030E1B27B4F6FC44A5B` |
| `m11-scenes-cards-100.png` | `992027AFA96FB6B98ADA371FCCBA0981038E840943E3BC4D8A94581DC47B2D20` |
| `m11-scene-detail-100.png` | `72E68D565F72CE8C9A88623547EA233128C1CC197699B9D185F9C4BA4FFBE38C` |
| `m11-canonical-escape-100.png` | `971CBDB08AA21E4BD1BC555B01B969104635901B28A12CA6454141D8D0CFF706` |
| `m11-scenes-200.png` | `C685EAE3830B2610D5203E0EEFA43121CAE9E0414B95FD621A23772989CFED5D` |
| `m11-scenes-cards-200.png` | `EBE6F36ACD51E8AC60F308B26469D72E4D6AC3F4AF49B5A9DD561A7C76F63FAD` |
| `m11-scene-detail-200.png` | `3645D2105F66E3853BABA4AD67C5B57855701E8C54A0B51513E9CAF6710F8331` |
| `m11-canonical-escape-200.png` | `FAAA42D43764103D00BB7A48B139CE133C1AF2930930D1D0CE2C41DDE95D1882` |
