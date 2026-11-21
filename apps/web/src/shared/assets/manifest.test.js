import { describe, expect, it } from "vitest";
import { assetManifest } from "./manifest.js";

describe("asset manifest", () => {
  it("keeps semantic dimensions and alt policy for shipped artwork", () => {
    expect(assetManifest.brandMark).toMatchObject({ width: 48, height: 48, decorative: false });
    expect(assetManifest.emptyLibrary).toMatchObject({ width: 320, height: 220, decorative: true, alt: "" });
    expect(assetManifest.brandMark.src).toMatch(/sourcelens-mark\.svg$/);
  });
});
