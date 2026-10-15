import { mount } from "svelte";
import App from "./App.svelte";
import { settleLanguage, useLanguageStrategies } from "./lib/language";
import "./app.css";

useLanguageStrategies();
settleLanguage();
mount(App, { target: document.getElementById("app")! });
