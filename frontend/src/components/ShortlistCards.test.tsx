import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CardVM, ShortlistVM } from "@/lib/viewmodels/contract";

import { ListingCard } from "./ListingCard";
import { ShortlistCards } from "./ShortlistCards";

const transit = {
  what: "Metro",
  value_text: "1.1 km",
  badge: "by route",
  full_label: "[OSM routing — precomputed 2026-09-01]",
  spoken: "",
};

function card(id: string, rank: number, locality = "Koramangala"): CardVM {
  return {
    listing_id: id,
    rank,
    locality,
    society_name: "Raheja Residency",
    rent: "₹32,000",
    deposit: "not stated",
    maintenance: "₹3,500",
    bhk_type: "2 BHK",
    square_footage: "1,150 sq ft (carpet)",
    floor: "3",
    parking: "not stated",
    furnishing: "Semi-furnished",
    amenities: ["Lift", "Power backup"],
    available_from: "1 Oct 2026",
    transit,
    your_commute: null,
  };
}

describe("ListingCard", () => {
  it("uses the locality as the heading and never says 'area'", () => {
    const { container } = render(<ListingCard card={card("a", 1)} />);
    expect(container.querySelector("h3")?.textContent).toBe("Koramangala");
    expect(container.textContent?.toLowerCase()).not.toContain("area");
    expect(container.textContent).toContain("sq ft");
  });

  it("shows 'not stated' for missing values and omits the commute row when absent", () => {
    const { container } = render(<ListingCard card={card("a", 1)} />);
    const notStated = Array.from(container.querySelectorAll("*")).filter(
      (n) => n.textContent === "not stated",
    );
    expect(notStated.length).toBeGreaterThanOrEqual(2);
    expect(container.textContent).not.toContain("Work");
  });
});

describe("ShortlistCards", () => {
  it("renders cards in the shortlist order and never sorts them", () => {
    const shortlist: ShortlistVM = {
      order: ["b", "a"],
      groups: [{ locality: "Koramangala", count: 2, cards: [card("b", 2), card("a", 1)] }],
      unknown_on: [],
    };
    render(<ShortlistCards shortlist={shortlist} />);
    const ids = screen.getAllByRole("article").map((el) => el.getAttribute("data-listing-id"));
    expect(ids).toEqual(["b", "a"]);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("Koramangala");
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("2");
  });

  it("offers the unknown-on group in the backend's words", () => {
    const shortlist: ShortlistVM = {
      order: ["a"],
      groups: [{ locality: "Koramangala", count: 1, cards: [card("a", 1)] }],
      unknown_on: [
        {
          field: "deposit",
          listing_ids: ["x", "y", "z"],
          spoken: "3 more where the deposit is not stated — want to see them?",
        },
      ],
    };
    render(<ShortlistCards shortlist={shortlist} />);
    expect(screen.getByText(/3 more where the deposit is not stated/)).toBeTruthy();
  });
});
