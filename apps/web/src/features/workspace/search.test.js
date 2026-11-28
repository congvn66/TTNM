import { describe, expect, it } from "vitest";
import { matchesQuery, searchText } from "./search.js";

describe("library search", () => {
  it("ignores accents and reads hyphens as spaces", () => {
    expect(searchText("Báo-cáo_mẫu Hương Lúa.pdf")).toBe("bao cao mau huong lua pdf");
    expect(matchesQuery("bao-cao-mau-huong-lua.pdf", "hương lúa")).toBe(true);
    expect(matchesQuery("bao-cao-mau-huong-lua.pdf", "bao cao")).toBe(true);
    expect(matchesQuery("Đầu tư Hà Nội.pdf", "dau tu")).toBe(true);
  });

  it("needs every word, in any order", () => {
    expect(matchesQuery("bctc-q3-2025.pdf", "2025 q3")).toBe(true);
    expect(matchesQuery("bctc-q3-2025.pdf", "q4")).toBe(false);
    expect(matchesQuery("anything", "   ")).toBe(true);
  });
});
