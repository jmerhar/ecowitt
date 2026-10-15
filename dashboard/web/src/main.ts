import { mount } from "svelte";
import App from "./App.svelte";
import { useLanguageStrategies } from "./lib/language";
import { getLocale } from "./paraglide/runtime.js";
import "./app.css";

useLanguageStrategies();
document.documentElement.lang = getLocale();
mount(App, { target: document.getElementById("app")! });
