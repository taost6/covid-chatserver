<template>
  <v-main class="landing-main">
    <v-container fluid class="landing-shell">
      <section class="hero-panel">
        <div class="hero-copy">
          <p class="eyebrow">Simulation Workspace</p>
          <h1 class="hero-title">COVID-19患者積極的疫学調査シミュレータ</h1>
          <p class="hero-lead">
            保健師役と患者役の対話、AI同士の自動対話、評価レポート生成、CBT形式の訓練をまとめて扱うアプリケーションです。
          </p>
        </div>

        <div class="hero-actions">
          <v-btn
            color="primary"
            size="x-large"
            rounded="xl"
            elevation="2"
            :to="{ name: 'chat' }"
          >
            自由選択モードを開く
          </v-btn>
        </div>
      </section>

      <section class="info-grid">
        <article class="info-card accent-blue">
          <p class="card-kicker">/training</p>
          <h2>自由選択モード</h2>
          <p>
            ロールと患者IDを選んで面談を開始します。通常対話、自動対話、評価レポート表示までここで扱います。
          </p>
        </article>

        <article class="info-card accent-amber">
          <p class="card-kicker">/cbt</p>
          <h2>CBTトレーニング</h2>
          <p>
            被験者向けトークンURL、課題の順次実行、結果確認を分離した導線です。訓練運用はこちらに集約されます。
          </p>
        </article>

        <article class="info-card accent-slate">
          <p class="card-kicker">Workflow</p>
          <h2>主な機能</h2>
          <ul>
            <li>患者AIとの聞き取り演習</li>
            <li>対話ログと評価レポートの確認</li>
            <li>IRT項目に基づく判定と集計</li>
            <li>CBT形式での反復トレーニング</li>
          </ul>
        </article>
      </section>
    </v-container>
  </v-main>
</template>

<style scoped>
.landing-main {
  --landing-navy: #12324a;
  --landing-ink: #1f2a37;
  --landing-paper: rgba(255, 255, 255, 0.84);
  --landing-line: rgba(18, 50, 74, 0.12);
  --landing-gold: #d7a63d;
  background:
    radial-gradient(circle at top left, rgba(215, 166, 61, 0.16), transparent 28%),
    radial-gradient(circle at bottom right, rgba(28, 100, 242, 0.12), transparent 30%),
    linear-gradient(160deg, #f6f1e7 0%, #edf4f8 52%, #f8fafc 100%);
  min-height: 100dvh;
}

.landing-shell {
  max-width: 1180px;
  padding: 40px 20px 56px;
}

.hero-panel {
  position: relative;
  overflow: hidden;
  padding: 40px 32px;
  border: 1px solid var(--landing-line);
  border-radius: 32px;
  background:
    linear-gradient(135deg, rgba(18, 50, 74, 0.96), rgba(24, 83, 119, 0.88)),
    var(--landing-navy);
  color: #f8fafc;
  box-shadow: 0 28px 60px rgba(18, 50, 74, 0.18);
}

.hero-panel::after {
  content: "";
  position: absolute;
  inset: auto -40px -60px auto;
  width: 220px;
  height: 220px;
  border-radius: 999px;
  background: radial-gradient(circle, rgba(215, 166, 61, 0.45), rgba(215, 166, 61, 0));
}

.hero-copy {
  position: relative;
  z-index: 1;
  max-width: 760px;
}

.eyebrow {
  margin: 0 0 10px;
  color: rgba(248, 250, 252, 0.7);
  font-size: 0.8rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.hero-title {
  margin: 0;
  color: #fffdf7;
  font-size: clamp(2rem, 4vw, 3.5rem);
  line-height: 1.08;
  letter-spacing: 0.02em;
}

.hero-lead {
  margin: 18px 0 0;
  max-width: 640px;
  color: rgba(248, 250, 252, 0.84);
  font-size: 1rem;
  line-height: 1.8;
}

.hero-actions {
  position: relative;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 28px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-top: 20px;
}

.info-card {
  min-height: 220px;
  padding: 24px 22px;
  border: 1px solid var(--landing-line);
  border-radius: 26px;
  background: var(--landing-paper);
  backdrop-filter: blur(12px);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.06);
}

.card-kicker {
  margin: 0 0 10px;
  color: var(--landing-navy);
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.info-card h2 {
  margin: 0 0 12px;
  color: var(--landing-ink);
  font-size: 1.3rem;
}

.info-card p,
.info-card li {
  color: #475569;
  line-height: 1.75;
}

.info-card ul {
  margin: 0;
  padding-left: 18px;
}

.accent-blue {
  border-top: 4px solid #2563eb;
}

.accent-amber {
  border-top: 4px solid var(--landing-gold);
}

.accent-slate {
  border-top: 4px solid #475569;
}

@media (max-width: 960px) {
  .info-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 600px) {
  .landing-shell {
    padding: 24px 14px 40px;
  }

  .hero-panel {
    padding: 28px 20px;
    border-radius: 24px;
  }

  .hero-actions {
    flex-direction: column;
  }
}
</style>
