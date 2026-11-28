/** Text for matching: no accents (đ counts as d), lower case, and "-", "_" or "." read as a space. */
export function searchText(value = "") {
  return String(value)
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/đ/g, "d").replace(/Đ/g, "d")
    .toLowerCase()
    .replace(/[-_.]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** True when every word of the query appears in the name, in any order. */
export function matchesQuery(name, query) {
  const words = searchText(query).split(" ").filter(Boolean);
  if (!words.length) return true;
  const text = searchText(name);
  return words.every((word) => text.includes(word));
}
