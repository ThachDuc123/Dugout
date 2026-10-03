# ⚽ FL26 AI Football Analytics

> An AI-powered football analytics application for **Football Life 26 (FL26)** — designed to monitor gameplay, analyze match behavior, study opponents, and generate data-driven predictions and tactical insights.

![Football](https://img.shields.io/badge/Football-Analytics-green)
![AI](https://img.shields.io/badge/AI-Analysis-purple)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?logo=javascript\&logoColor=black)
![PWA](https://img.shields.io/badge/PWA-Supported-blue)

---

##  Overview

**FL26 AI Football Analytics** is a football analysis application designed around **Football Life 26 gameplay**.

The idea is to transform a football match from something that is only watched into something that can be **measured, analyzed, and interpreted**.

The application can be developed around three main questions:

> **What is happening?**

> **Why is it happening?**

> **What is likely to happen next?**

The system combines match monitoring, data collection, statistical analysis, opponent profiling, and AI-based prediction to build a more complete picture of the game.

---

##  Core Concept

```text
                 Football Life 26
                        │
                        ▼
              ┌───────────────────┐
              │  Match Monitoring │
              └─────────┬─────────┘
                        │
                        ▼
              ┌───────────────────┐
              │   Data Collection │
              └─────────┬─────────┘
                        │
             ┌──────────┼──────────┐
             ▼          ▼          ▼
        Match Data   Player Data  Events
             │          │          │
             └──────────┼──────────┘
                        ▼
              ┌───────────────────┐
              │  AI Analysis      │
              └─────────┬─────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
      Player        Opponent      Match State
      Analysis      Analysis       Analysis
          │             │             │
          └─────────────┼─────────────┘
                        ▼
              ┌───────────────────┐
              │ Prediction Engine │
              └─────────┬─────────┘
                        ▼
              ┌───────────────────┐
              │ Tactical Insights │
              └───────────────────┘
```

---

#  What Can Be Analyzed?

##  Player Analysis

The system can build a profile of how the player approaches matches.

Possible signals include:

* Possession patterns
* Passing tendencies
* Attacking frequency
* Defensive behavior
* Shot selection
* Goal-scoring patterns
* Conceded-goal patterns
* Match tempo
* Performance across matches

Instead of looking at one match independently:

```text
Match 1
   ↓
Match 2
   ↓
Match 3
   ↓
Match 4
   ↓
Historical Player Profile
```

The system can identify recurring patterns.

---

#  Opponent Analysis

One of the main goals is to create an **opponent profile**.

For example:

```text
Opponent Profile
│
├── Preferred Formation
├── Attacking Style
├── Defensive Style
├── Passing Tendencies
├── Build-up Pattern
├── Pressure Behavior
├── Preferred Attacking Side
├── Defensive Weaknesses
└── Recent Match Trends
```

Instead of asking only:

> “Who is the opponent?”

the system attempts to answer:

> “How does this opponent actually play?”

---

#  AI Match Analysis

The AI layer can combine historical and current-match information.

```text
Historical Matches
        │
        ▼
   Feature Extraction
        │
        ▼
   Opponent Profile
        │
        ├──────────────┐
        │              │
        ▼              ▼
 Current Match     Historical Data
        │              │
        └──────┬───────┘
               ▼
          AI Analysis
               │
               ▼
        Match Prediction
```

The prediction system can potentially estimate things such as:

* Expected match tendencies
* Likely attacking patterns
* Potential tactical changes
* Player performance trends
* Match-state changes
* Possible scoring scenarios

These predictions should be treated as **data-driven estimates**, not guaranteed outcomes.

---

#  Match State Analysis

Football is dynamic, so analyzing only the final score loses a lot of information.

The application can track the match as a sequence:

```text
Kickoff
   │
   ▼
Early Match
   │
   ▼
Possession / Attacks
   │
   ▼
Goal / Conceded Goal
   │
   ▼
Tactical Change
   │
   ▼
Late Match
   │
   ▼
Final Result
```

This allows the system to investigate **how the match developed**, rather than only recording the final result.

---

#  Prediction Engine

The prediction component can use historical observations and current-match features to generate estimates.

Conceptually:

```text
Historical Data
      +
Opponent Profile
      +
Current Match State
      +
Player Performance
      │
      ▼
┌─────────────────────┐
│    AI Prediction    │
└──────────┬──────────┘
           ▼
 ┌─────────────────────┐
 │ Predicted Scenarios │
 └─────────────────────┘
```

Possible prediction outputs:

| Analysis           | Example                         |
| ------------------ | ------------------------------- |
| Match tendency     | Attacking / defensive           |
| Goal tendency      | Higher / lower scoring scenario |
| Opponent behavior  | Likely tactical pattern         |
| Player performance | Expected performance trend      |
| Match state        | Current momentum / pressure     |
| Tactical response  | Possible adjustment             |

---

#  From Raw Data to Insight

The important part of the application is not simply collecting statistics.

The pipeline is:

```text
Raw Gameplay
     ↓
Data Collection
     ↓
Data Cleaning
     ↓
Feature Extraction
     ↓
Statistical Analysis
     ↓
Opponent Profiling
     ↓
AI Model
     ↓
Prediction
     ↓
Human-readable Insight
```

For example:

```text
Raw Data
   ↓
Opponent repeatedly attacks through one side
   ↓
Pattern detected
   ↓
Historical matches confirm the pattern
   ↓
AI identifies recurring tendency
   ↓
System generates an analytical insight
```

---

#  Application Architecture

```text
┌─────────────────────────────────────────┐
│            Football Life 26             │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│             Data Collection             │
│                                         │
│ Match Events • Statistics • Gameplay    │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│            Analysis Engine               │
│                                         │
│ Statistics • Trends • Patterns          │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│             AI Layer                    │
│                                         │
│ Prediction • Classification • Profiling │
└───────────────────┬─────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│          Visualization / UI             │
│                                         │
│ Dashboard • Charts • Insights           │
└─────────────────────────────────────────┘
```

---

#  Dashboard Concept

The application can present information through a football analytics dashboard:

```text
┌─────────────────────────────────────────┐
│           FL26 AI ANALYTICS             │
├─────────────────────────────────────────┤
│                                         │
│  MATCH OVERVIEW                         │
│  ───────────────────────────────────    │
│  Player              Opponent           │
│  Performance         Profile            │
│                                         │
├─────────────────────────────────────────┤
│                                         │
│  📊 Match Statistics                    │
│                                         │
├─────────────────────────────────────────┤
│                                         │
│  🧠 AI Analysis                         │
│                                         │
├─────────────────────────────────────────┤
│                                         │
│  🔮 Predictions                         │
│                                         │
└─────────────────────────────────────────┘
```

---

#  Project Structure

The current repository contains the main web/application layer together with several project/data directories. ([github.com](https://github.com/ThachDuc123/Dugout))

```text
FL26-AI-Football-Analytics/
│
├── app/
│
├── data3/
│
├── dugout2/
│
├── m/
│
├── web2/
│
├── app.js
├── index.html
├── style.css
├── sw.js
│
├── icon.png
├── icon-512.png
│
└── README.md
```

---

#  Technology

The current repository contains a web application structure based around:

| Technology     | Role                    |
| -------------- | ----------------------- |
| HTML5          | Interface               |
| CSS3           | Styling                 |
| JavaScript     | Application logic       |
| Service Worker | PWA functionality       |
| Data modules   | Match / analysis data   |
| AI layer       | Analysis and prediction |

The exact AI model should be documented here once the prediction implementation is finalized.

---

#  Getting Started

### Clone

```bash
git clone https://github.com/ThachDuc123/Dugout.git
cd Dugout
```

### Run locally

Because this is a web application, serve the project through a local HTTP server.

For example:

```bash
python -m http.server 8000
```

Then open:

```text
http://localhost:8000
```

---

#  AI Development Roadmap

The AI system can progressively evolve through several stages.

### Stage 1 — Statistics

```text
Match Data
    ↓
Descriptive Statistics
    ↓
Player / Opponent Profile
```

### Stage 2 — Pattern Detection

```text
Historical Matches
       ↓
Feature Extraction
       ↓
Pattern Detection
       ↓
Opponent Tendencies
```

### Stage 3 — Machine Learning

```text
Historical Data
       ↓
Training Dataset
       ↓
ML Model
       ↓
Prediction
```

### Stage 4 — Continuous Analysis

```text
Current Match
      +
Historical Profile
      +
Opponent Behavior
      ↓
Real-time Analysis
      ↓
Updated Prediction
```

---

#  Future Improvements

* [ ] Automatic FL26 match-data collection
* [ ] Real-time match monitoring
* [ ] Player performance tracking
* [ ] Opponent profiling
* [ ] Formation recognition
* [ ] Tactical pattern detection
* [ ] Historical match database
* [ ] AI-based opponent analysis
* [ ] Match prediction
* [ ] Player performance prediction
* [ ] Interactive analytics dashboard
* [ ] Match timeline visualization
* [ ] Advanced ML models
* [ ] Model evaluation and accuracy benchmarks
* [ ] Export match reports

---

#  Prediction Philosophy

The purpose of the AI system is **analysis and estimation**, not guaranteed prediction.

A prediction should be presented together with the information behind it:

```text
Prediction
    +
Supporting Data
    +
Detected Pattern
    +
Confidence
```

This makes the system more transparent and allows users to understand **why** an AI prediction was generated.

---

#  Project Vision

The long-term goal is to turn **Football Life 26 gameplay data into an analytical dataset** and build an AI assistant capable of understanding recurring football-game patterns.

```text
                  FL26
                   │
                   ▼
             Gameplay Data
                   │
                   ▼
              AI Analyst
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
    Player      Opponent     Match
    Analysis    Analysis     Analysis
       │           │           │
       └───────────┼───────────┘
                   ▼
              Predictions
                   │
                   ▼
            Tactical Insights
```

> **Watch the match → collect the data → understand the pattern → analyze the opponent → generate an AI-based prediction.**

---

##  Author

**ThachDuc123**

GitHub:
https://github.com/ThachDuc123

---

##  Project

If you find the project interesting, consider giving the repository a ⭐.
