class Novanode < Formula
  desc "AI token usage status CLI for Claude, Codex and Cursor"
  homepage "https://github.com/nachogonz/novanode-resgistry#readme"
  url "https://github.com/nachogonz/novanode-resgistry/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "451210713a57d8dfa29ef8b737c30ac9b8e3af5f7d64a89c5470bd635ae771bd"
  license "MIT"

  depends_on "python@3.12"

  def install
    libexec.install Dir["*"]

    (bin/"nn-usage").write <<~SH
      #!/bin/bash
      export PATH="#{formula_opt_bin("python@3.12")}:$PATH"
      exec "#{libexec}/bin/nn-usage" "$@"
    SH

    bin.install_symlink "nn-usage" => "novanode"
  end

  test do
    assert_equal version.to_s, shell_output("#{bin}/novanode --version").strip
    assert_equal version.to_s, shell_output("#{bin}/nn-usage --version").strip
    assert_match "Usage:", shell_output("#{bin}/nn-usage --help")
  end
end
