import { describe, expect, it } from "vitest";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import config from "../tailwind.config";

describe("theme accent colors", () => {
  it("generates primary button backgrounds and accent shades", async () => {
    const result = await postcss([
      tailwindcss({
        ...config,
        content: [{ raw: "bg-cyan-400 hover:bg-cyan-300 text-cyan-300 bg-lime-400 bg-amber-400 bg-cyan", extension: "html" }]
      })
    ]).process("@tailwind utilities;", { from: undefined });

    expect(result.css).toContain(".bg-cyan-400");
    expect(result.css).toContain(".hover\\:bg-cyan-300:hover");
    expect(result.css).toContain(".text-cyan-300");
    expect(result.css).toContain(".bg-lime-400");
    expect(result.css).toContain(".bg-amber-400");
    expect(result.css).toContain(".bg-cyan {");
  });
});
