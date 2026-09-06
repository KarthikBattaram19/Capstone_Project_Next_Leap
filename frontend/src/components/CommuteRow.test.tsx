import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CommuteRow } from "./CommuteRow";

describe("CommuteRow", () => {
  it("straight-line rows are visually distinct and carry the full label", () => {
    render(
      <CommuteRow
        row={{
          what: "Work",
          value_text: "6 km",
          badge: "straight-line",
          full_label: "[Straight-line from coordinates — computed now]",
          spoken: "",
        }}
      />,
    );
    const badge = screen.getByText("straight-line");
    expect(badge.className).toContain("badge--straight");
    expect(badge.closest("li")?.getAttribute("title")).toContain("computed now");
  });

  it("by-route rows carry the route badge class", () => {
    render(
      <CommuteRow
        row={{ what: "Metro", value_text: "1.1 km", badge: "by route", full_label: "[OSM]", spoken: "" }}
      />,
    );
    expect(screen.getByText("by route").className).toContain("badge--route");
  });

  it("not stated rows render no badge and no zero", () => {
    render(
      <CommuteRow
        row={{
          what: "Metro",
          value_text: "not stated",
          badge: "",
          full_label: "[OSM — precomputed 2026-09-02]",
          spoken: "",
        }}
      />,
    );
    expect(screen.getByText("not stated")).toBeTruthy();
    expect(screen.queryByText("0 km")).toBeNull();
    expect(document.querySelector(".badge")).toBeNull();
  });
});
