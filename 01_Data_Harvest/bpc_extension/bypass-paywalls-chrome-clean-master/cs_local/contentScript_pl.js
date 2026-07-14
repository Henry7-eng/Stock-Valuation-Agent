//"use strict";

var pl_ringier_domains = ['auto-swiat.pl', 'businessinsider.com.pl', 'forbes.pl', 'komputerswiat.pl', 'newsweek.pl', 'onet.pl'];

cs_default = function (bg2csData = '') {

if (bg2csData && bg2csData.cs_param)
  cs_param = bg2csData.cs_param;

if (!(csDone || csDoneOnce)) {

if (window.location.hostname.match(/\.pl$/) || matchDomain(['parkiet.com', 'wyborcza.biz'])) {//poland

if (matchDomain('pb.pl')) {
  let paywall = document.querySelector('div.paywall');
  if (paywall) {
    paywall.classList.remove('paywall');
    let article_hidden = paywall.querySelector('section.o-article-content');
    if (article_hidden)
      article_hidden.removeAttribute('class');
    let loader = document.querySelector('div.o-piano-template-loader-box');
    removeDOMElement(loader);
  }
}

else if (matchDomain(pl_ringier_domains)) {
  let premium = document.querySelector('div.contentPremium[style]');
  if (premium) {
    premium.removeAttribute('class');
    premium.removeAttribute('style');
    premium.parentNode.removeAttribute('class');
  }
  if (matchDomain('newsweek.pl')) {
    let audio_tts = document.querySelector('button.pw-ap__button[disabled]');
    if (audio_tts)
      audio_tts.removeAttribute('disabled');
    let podcast_locked = document.querySelector('div.embed__podcastPlayer.contentPremium-locked');
    if (podcast_locked)
      podcast_locked.classList.remove('contentPremium-locked');
    let podcast_video = document.querySelector('div.videoPremiumWrapper > div.embed__mainVideoWrapper');
    if (podcast_video) {
      podcast_video.removeAttribute('class');
      podcast_video.parentNode.removeAttribute('class');
    }
  }
  let ads = 'div.adPlaceholder , div[class^="Ad"][class*="Placeholder_"], div[data-placeholder-caption], div[data-run-module$=".floatingAd"], aside[data-ad-container], aside.adsContainer, [class^="pwAds"], .hide-for-paying, div.onet-ad, div.bottomBar, ad-default, ad-floating-group, aside.ods-ads__ad-space';
  hideDOMStyle(ads);
}

else if (matchDomain('polityka.pl')) {
  let paywall = document.querySelector('div.cg-article-salebox');
  if (paywall) {
    removeDOMElement(paywall);
    let elem_hidden = document.querySelectorAll('div.cg_article_meat > [style]');
    for (let elem of elem_hidden)
      elem.removeAttribute('style');
    let fade = document.querySelector('article.article_status-cut');
    if (fade)
      fade.classList.remove('article_status-cut');
  }
}

else if (matchDomain(['rp.pl', 'parkiet.com'])) {
  let paywall = document.querySelector('div.paywallComp');
  if (paywall) {
    removeDOMElement(paywall);
    let article = document.querySelector('div.article--content');
    if (article) {
      let url = window.location.href;
      article.firstChild.before(googleSearchToolLink(url));
    }
  }
}

else if (matchDomain(['wyborcza.biz', 'wyborcza.pl', 'wysokieobcasy.pl', 'magazyn-kuchnia.pl'])) {
  func_post = function () {
    let block_quotes = document.querySelectorAll('blockquote > a[href]');
    for (let elem of block_quotes) {
      if (!elem.innerText.trim())
        elem.innerText = elem.href;
    }
    let empty_spans = document.querySelectorAll('figure > a > span:empty');
    removeDOMElement(...empty_spans);
    let paywall = document.querySelector('span[style*="linear-gradient"]');
    if (paywall) {
      removeDOMElement(paywall);
      let article = document.querySelector('div.mrf-article-body');
      if (article)
        article.before(googleSearchToolLink(url));
    }
    let ads = 'div[style^="min-height:"]';
    hideDOMStyle(ads, 2);
  }
  let url = window.location.href;
  getArchive(url, 'div.article--content-fadeout', {rm_attrib: 'class'}, 'div.container[class*="pt"]', '', 'div.body > div:not([style*="background-color:"]):not([old-position]):not([name]):not([id])');
  let ads = 'div[id^="adUnit"], div[id^="ads-"]';
  hideDOMStyle(ads);
}

else
  csDone = true;
}

} // end csDone(Once)

ads_hide();
leaky_paywall_unhide();

} // end cs_default function
