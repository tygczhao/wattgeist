// Property tests for formatting and axis ticks (fast-check): ticks always cover the data and formatting never prints NaN.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { kwh, money, niceTicks, ordinal, watts } from "./format";

describe("niceTicks", () => {
  it("starts at zero, increases evenly and covers the max", () => {
    fc.assert(
      fc.property(fc.double({ min: 0.001, max: 1e7, noNaN: true }), fc.integer({ min: 2, max: 8 }), (max, count) => {
        const t = niceTicks(max, count);
        expect(t[0]).toBe(0);
        expect(t[t.length - 1]).toBeGreaterThanOrEqual(max);
        const step = t[1] - t[0];
        for (let i = 1; i < t.length; i++) expect(t[i] - t[i - 1]).toBeCloseTo(step, 6);
        expect(t.length).toBeLessThanOrEqual(count * 3 + 2);
      }),
    );
  });
});

describe("formatters", () => {
  it("never print NaN or undefined", () => {
    fc.assert(
      fc.property(fc.double({ min: -1e9, max: 1e9, noNaN: true }), (v) => {
        for (const s of [watts(v), kwh(v), money(v)]) {
          expect(s).not.toMatch(/NaN|undefined|Infinity/);
        }
      }),
    );
  });
  it("money keeps two decimals and the sign", () => {
    expect(money(1337.3)).toBe("£1,337.30");
    expect(money(-2.5, "USD")).toBe("−$2.50");
  });
  it("ordinal suffixes", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 98, 101].map(ordinal)).toEqual(
      ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "98th", "101st"],
    );
  });
});
