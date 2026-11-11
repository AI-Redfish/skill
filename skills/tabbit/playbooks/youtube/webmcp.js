// Adapted from TabbitAi/tabbit-webmcp @
// 13fef01b80ce371aeb53cf92bd3c677bb25c24bd. See ../WEBMCP-SOURCE.md for
// provenance and limitations. Each function is a standalone page.evaluate
// callback; nothing executes on load.

// 读取首页信息流 — read. 滚动并读取 YouTube
// 首页当前信息流中的视频、Shorts、封面、标题、频道、时长、观看数和发布时间。
async function youtube_get_home_feed(rawInput = {}) {
  const youtubeAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        ['www.youtube.com', 'm.youtube.com'].includes(url.hostname) &&
        (url.pathname === '/' ||
         (url.pathname === '/watch' &&
          /^[\w-]{6,20}$/.test(url.searchParams.get('v') ?? ''))),
    toolNames: (url) => url.pathname === '/' ?
        ['youtube_get_home_feed'] :
        [
          'youtube_get_video_download_urls', 'youtube_get_video_comments',
          'youtube_get_video_details', 'youtube_get_subtitle_file'
        ]
  };
  const routeUrl = new URL(location.href);
  if (!youtubeAdapter.matches(routeUrl) ||
      !youtubeAdapter.toolNames(routeUrl).includes('youtube_get_home_feed'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported YouTube page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['maxVideos', 'maxScrolls'].includes(key)) &&
        (!('maxVideos' in rawInput) ||
         (Number.isInteger(rawInput['maxVideos']) &&
          rawInput['maxVideos'] >= 1 && rawInput['maxVideos'] <= 200)) &&
        (!('maxScrolls' in rawInput) ||
         (Number.isInteger(rawInput['maxScrolls']) &&
          rawInput['maxScrolls'] >= 0 && rawInput['maxScrolls'] <= 50))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const runsText = (value) => clean(
        value?.simpleText || value?.content ||
        value?.runs?.map((entry) => entry.text).join('') || '');
    const parseCount = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*([KMB]|万|萬|亿|億)?/i);
      if (!match)
        return null;
      const base = Number(match[1]);
      if (!Number.isFinite(base))
        return null;
      const multipliers =
          {k: 1e3, m: 1e6, b: 1e9, '万': 1e4, '萬': 1e4, '亿': 1e8, '億': 1e8};
      return Math.round(
          base * (multipliers[(match[2] || '').toLowerCase()] || 1));
    };
    const clockSeconds = (value) => {
      const clock = clean(value);
      if (!/^\d+(?::\d{2}){1,2}$/.test(clock))
        return null;
      const parts = clock.split(':').map(Number);
      return parts.reduce((total, part) => total * 60 + part, 0);
    };
    const youtubeUrl = (value) => {
      const href = absolute(value);
      if (!href)
        return '';
      try {
        const parsed = new URL(href);
        if (!['www.youtube.com', 'm.youtube.com'].includes(parsed.hostname))
          return '';
        if (parsed.pathname === '/watch') {
          const videoId = parsed.searchParams.get('v');
          return videoId ?
              `${parsed.origin}/watch?v=${encodeURIComponent(videoId)}` :
              '';
        }
        const shortId = parsed.pathname.match(/^\/shorts\/([\w-]{6,20})/)?.[1];
        return shortId ? `${parsed.origin}/shorts/${shortId}` : '';
      } catch {
        return '';
      }
    };
    const videoIdFromUrl = (value) => {
      try {
        const parsed = new URL(value);
        return parsed.pathname === '/watch' ?
            parsed.searchParams.get('v') || '' :
            parsed.pathname.match(/^\/shorts\/([\w-]{6,20})/)?.[1] || '';
      } catch {
        return '';
      }
    };
    const largestThumbnail = (sources) => Array.isArray(sources) ?
        sources.filter((entry) => entry?.url)
                .sort(
                    (left, right) =>
                        Number(right.width || 0) - Number(left.width || 0))[0]
                ?.url ||
            '' :
        '';
    const lockupVideo = (model) => {
      if (!model || typeof model !== 'object')
        return null;
      const metadata = model.metadata?.lockupMetadataViewModel || {};
      const rows =
          metadata.metadata?.contentMetadataViewModel?.metadataRows || [];
      const parts = rows.flatMap((row) => row?.metadataParts || [])
                        .map((part) => runsText(part?.text))
                        .filter(Boolean);
      const command =
          model.rendererContext?.commandContext?.onTap?.innertubeCommand ||
          model.itemPlayback?.inlinePlayerData?.onSelect?.innertubeCommand ||
          model.itemPlayback?.inlinePlayerData?.onVisible?.innertubeCommand;
      const path = command?.commandMetadata?.webCommandMetadata?.url ||
          (command?.watchEndpoint?.videoId ?
               `/watch?v=${command.watchEndpoint.videoId}` :
               '');
      const url = youtubeUrl(path);
      const id = videoIdFromUrl(url);
      if (!url || !id)
        return null;
      const durationText =
          clean(model.contentImage?.thumbnailViewModel?.overlays?.[0]
                    ?.thumbnailBottomOverlayViewModel?.badges?.[0]
                    ?.thumbnailBadgeViewModel?.text);
      const channel = parts[0] ||
          clean(metadata.image?.decoratedAvatarViewModel?.a11yLabel)
              .replace(/^Go to channel\s+/i, '');
      const viewCountText =
          parts.find(
              (entry) => /views?|观看|觀看|次播放/i.test(entry)) ||
          null;
      const publishedText =
          parts.find((entry) => entry !== channel && entry !== viewCountText) ||
          null;
      return {
        id,
        type: new URL(url).pathname.startsWith('/shorts/') ? 'short' : 'video',
        url,
        title: runsText(metadata.title),
        thumbnailUrl:
            absolute(largestThumbnail(
                model.contentImage?.thumbnailViewModel?.image?.sources)) ||
            null,
        channel: {
          name: channel || null,
          id: metadata.image?.decoratedAvatarViewModel?.rendererContext
                  ?.commandContext?.onTap?.innertubeCommand?.browseEndpoint
                  ?.browseId ||
              null
        },
        durationText: durationText || null,
        durationSeconds: clockSeconds(durationText),
        viewCountText,
        viewCount: parseCount(viewCountText),
        publishedText,
        likeCount: null
      };
    };
    const rendererVideo = (renderer) => {
      if (!renderer || typeof renderer !== 'object')
        return null;
      const id = clean(renderer.videoId);
      const url = youtubeUrl(
          renderer.navigationEndpoint?.commandMetadata?.webCommandMetadata
              ?.url ||
          (id ? `/watch?v=${id}` : ''));
      if (!id || !url)
        return null;
      const durationText = runsText(renderer.lengthText) ||
          runsText(renderer.thumbnailOverlays
                       ?.find(
                           (entry) => entry.thumbnailOverlayTimeStatusRenderer)
                       ?.thumbnailOverlayTimeStatusRenderer?.text);
      const viewCountText =
          runsText(renderer.viewCountText || renderer.shortViewCountText) ||
          null;
      return {
        id,
        type: 'video',
        url,
        title: runsText(renderer.title),
        thumbnailUrl:
            absolute(largestThumbnail(renderer.thumbnail?.thumbnails)) || null,
        channel: {
          name:
              runsText(renderer.ownerText || renderer.shortBylineText) || null,
          id: renderer.ownerText?.runs?.[0]
                  ?.navigationEndpoint?.browseEndpoint?.browseId ||
              null
        },
        durationText: durationText || null,
        durationSeconds: clockSeconds(durationText),
        viewCountText,
        viewCount: parseCount(viewCountText),
        publishedText: runsText(renderer.publishedTimeText) || null,
        likeCount: null
      };
    };
    const domVideo = (card) => {
      if (card.querySelector(
              'ytd-ad-slot-renderer, ytd-in-feed-ad-layout-renderer, yt-collection-thumbnail-view-model'))
        return null;
      const anchors =
          Array.from(card.querySelectorAll('a[href]'))
              .filter((entry) => youtubeUrl(entry.getAttribute('href')));
      const titleAnchor =
          anchors.find(
              (entry) => entry.matches(
                  '.ytLockupMetadataViewModelTitle, #video-title-link, #video-title')) ||
          anchors
              .filter(
                  (entry) => clean(entry.title || entry.textContent).length > 5)
              .sort(
                  (left, right) =>
                      clean(right.title || right.textContent).length -
                      clean(left.title || left.textContent).length)[0];
      const url = youtubeUrl(
          titleAnchor?.getAttribute('href') ||
          anchors[0]?.getAttribute('href'));
      const id = videoIdFromUrl(url);
      const title = clean(titleAnchor?.title || titleAnchor?.textContent);
      if (!url || !id || !title)
        return null;
      const author = Array.from(card.querySelectorAll('a[href]'))
                         .find(
                             (entry) => /^\/(?:@|channel\/|c\/|user\/)/.test(
                                            entry.getAttribute('href') || '') &&
                                 clean(entry.textContent));
      const metadata =
          Array
              .from(card.querySelectorAll(
                  '.ytContentMetadataViewModelMetadataText, #metadata-line span, .inline-metadata-item'))
              .map((entry) => clean(entry.textContent))
              .filter(Boolean);
      const durationText = clean(
          card.querySelector(
                  '.ytBadgeShapeText, ytd-thumbnail-overlay-time-status-renderer, badge-shape')
              ?.textContent);
      const viewCountText =
          metadata.find(
              (entry) => /views?|观看|觀看|次播放/i.test(entry)) ||
          null;
      const image =
          Array.from(card.querySelectorAll('img'))
              .find(
                  (entry) => /(?:ytimg\.com|ggpht\.com)\/vi(?:_webp)?\//.test(
                      entry.currentSrc || entry.src));
      return {
        id,
        type: new URL(url).pathname.startsWith('/shorts/') ? 'short' : 'video',
        url,
        title,
        thumbnailUrl: absolute(image?.currentSrc || image?.src) || null,
        channel: {
          name: clean(author?.textContent) || null,
          id: author?.getAttribute('href')
                  ?.match(/^\/channel\/([^/?]+)/)
                  ?.[1] ||
              null
        },
        durationText: durationText || null,
        durationSeconds: clockSeconds(durationText),
        viewCountText,
        viewCount: parseCount(viewCountText),
        publishedText: metadata.find(
                           (entry) => entry !== viewCountText &&
                               entry !== clean(author?.textContent)) ||
            null,
        likeCount: null
      };
    };
    const videoFromCard = (card) => {
      const data = card.data;
      const lockup = data?.content?.lockupViewModel || data?.lockupViewModel;
      // Collection watch links start their first video; their metadata
      // describes the collection.
      if (lockup?.contentType &&
          lockup.contentType !== 'LOCKUP_CONTENT_TYPE_VIDEO')
        return null;
      return lockupVideo(lockup) ||
          rendererVideo(data?.content?.videoRenderer || data?.videoRenderer) ||
          domVideo(card);
    };
    {
      if (location.pathname !== '/')
        throw new Error('UNSUPPORTED_ROUTE: 该操作只在 YouTube 首页可用。');
      const maxVideos =
          Math.min(200, Math.max(1, Number(input.maxVideos ?? 100)));
      const maxScrolls =
          Math.min(50, Math.max(0, Number(input.maxScrolls ?? 20)));
      const originalY = window.scrollY;
      const collected = new Map();
      let scrolls = 0;
      let idle = 0;
      const collect = () => {
        const before = collected.size;
        const cards = Array.from(document.querySelectorAll(
            'ytd-rich-item-renderer, ytd-video-renderer'));
        for (const card of cards) {
          const video = videoFromCard(card);
          if (video && !collected.has(video.id))
            collected.set(video.id, video);
          if (collected.size >= maxVideos)
            break;
        }
        return collected.size - before;
      };
      collect();
      while (collected.size < maxVideos && scrolls < maxScrolls && idle < 3) {
        const beforeHeight = document.documentElement.scrollHeight;
        window.scrollBy(
            {top: Math.max(720, window.innerHeight * 0.85), behavior: 'auto'});
        await pause(500);
        const added = collect();
        scrolls += 1;
        const atEnd = window.scrollY + window.innerHeight >=
            document.documentElement.scrollHeight - 8;
        idle = added === 0 &&
                (atEnd ||
                 document.documentElement.scrollHeight === beforeHeight) ?
            idle + 1 :
            0;
      }
      const items = Array.from(collected.values()).slice(0, maxVideos);
      const truncated =
          collected.size >= maxVideos || (scrolls >= maxScrolls && idle < 3);
      window.scrollTo({top: originalY, behavior: 'auto'});
      await pause(80);
      return {
        data: {
          items,
          count: items.length,
          scrolls,
          truncated,
          likeCountAvailable: false
        },
        warnings: [
          'YouTube 首页不展示点赞数，因此每项 likeCount 为 null。',
          ...(truncated ?
                  ['YouTube 首页按需加载；结果达到调用上限，truncated=true。'] :
                  [])
        ]
      };
    }
  }
}


// 获取视频下载地址 — read.
// 读取当前播放器直接提供的临时媒体地址和格式信息；不会破解签名或 DRM。
async function youtube_get_video_download_urls(rawInput = {}) {
  const youtubeAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        ['www.youtube.com', 'm.youtube.com'].includes(url.hostname) &&
        (url.pathname === '/' ||
         (url.pathname === '/watch' &&
          /^[\w-]{6,20}$/.test(url.searchParams.get('v') ?? ''))),
    toolNames: (url) => url.pathname === '/' ?
        ['youtube_get_home_feed'] :
        [
          'youtube_get_video_download_urls', 'youtube_get_video_comments',
          'youtube_get_video_details', 'youtube_get_subtitle_file'
        ]
  };
  const routeUrl = new URL(location.href);
  if (!youtubeAdapter.matches(routeUrl) ||
      !youtubeAdapter.toolNames(routeUrl).includes(
          'youtube_get_video_download_urls'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported YouTube page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['type', 'maxResults'].includes(key)) &&
        (!('type' in rawInput) ||
         (typeof rawInput['type'] === 'string' &&
          ['all', 'muxed', 'video', 'audio'].includes(rawInput['type']))) &&
        (!('maxResults' in rawInput) ||
         (Number.isInteger(rawInput['maxResults']) &&
          rawInput['maxResults'] >= 1 && rawInput['maxResults'] <= 100))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/\s+/g, ' ')
                                 .trim();
    if (location.pathname !== '/watch')
      throw new Error('UNSUPPORTED_ROUTE: 该操作只在 YouTube 视频详情页可用。');
    const expectedVideoId = new URL(location.href).searchParams.get('v') || '';
    const normalizePlayer = (entry) => {
      if (typeof entry !== 'string')
        return entry;
      try {
        return JSON.parse(entry);
      } catch {
        return null;
      }
    };
    const playerCandidates = [
      win.ytInitialPlayerResponse,
      win.ytplayer?.config?.args?.raw_player_response,
      document.querySelector('ytd-watch-flexy')?.playerData,
      document.querySelector('ytd-watch-flexy')?.data?.playerData
    ].map(normalizePlayer);
    const player =
        playerCandidates.find(
            (entry) => entry?.videoDetails?.videoId === expectedVideoId) ||
        playerCandidates.find((entry) => entry?.videoDetails) || {};
    const details = player.videoDetails || {};
    const microformat = player.microformat?.playerMicroformatRenderer || {};
    const streaming = player.streamingData || {};
    const rawFormats =
        [...(streaming.formats || []), ...(streaming.adaptiveFormats || [])];
    const canonicalUrl =
        `${location.origin}/watch?v=${encodeURIComponent(expectedVideoId)}`;
    {
      if (Array.from(document.querySelectorAll('video'))
              .some((element) => element.mediaKeys)) {
        return {
          data: null,
          error: {
            code: 'DRM_PROTECTED',
            message: '当前媒体受 DRM 保护，不返回下载地址。',
            recoverable: false
          }
        };
      }
      const requestedType = clean(input.type || 'all');
      const maxResults =
          Math.min(100, Math.max(1, Number(input.maxResults ?? 50)));
      const matchingItems = rawFormats.flatMap((entry) => {
        const url = absolute(entry.url);
        if (!url)
          return [];
        let parsed;
        try {
          parsed = new URL(url);
        } catch {
          return [];
        }
        if (parsed.protocol !== 'https:' ||
            !(parsed.hostname === 'youtube.com' ||
              parsed.hostname.endsWith('.youtube.com') ||
              parsed.hostname === 'googlevideo.com' ||
              parsed.hostname.endsWith('.googlevideo.com')))
          return [];
        const mimeType = clean(entry.mimeType);
        const mediaType = mimeType.startsWith('audio/') ? 'audio' : 'video';
        const muxed = mediaType === 'video' &&
            Boolean(entry.audioQuality || entry.audioChannels);
        if (requestedType === 'muxed' && !muxed)
          return [];
        if (requestedType === 'audio' && mediaType !== 'audio')
          return [];
        if (requestedType === 'video' && (mediaType !== 'video' || muxed))
          return [];
        const expires = Number(parsed.searchParams.get('expire'));
        return [{
          itag: Number(entry.itag),
          url,
          mediaType,
          muxed,
          mimeType: mimeType.split(';')[0] || null,
          codecs: mimeType.match(/codecs="([^"]+)"/)?.[1] || null,
          quality:
              entry.qualityLabel || entry.audioQuality || entry.quality || null,
          width: Number(entry.width) || null,
          height: Number(entry.height) || null,
          fps: Number(entry.fps) || null,
          bitrate: Number(entry.bitrate) || null,
          audioSampleRate: Number(entry.audioSampleRate) || null,
          audioChannels: Number(entry.audioChannels) || null,
          contentLength: Number(entry.contentLength) || null,
          durationMs: Number(entry.approxDurationMs) || null,
          expiresAt: Number.isFinite(expires) && expires > 0 ?
              new Date(expires * 1000).toISOString() :
              null
        }];
      });
      const items = matchingItems.slice(0, maxResults);
      if (!items.length)
        return {
          data: {
            availableFormatCount: rawFormats.length,
            directFormatCount: rawFormats.filter((entry) => entry.url).length
          },
          error: {
            code: 'DOWNLOAD_UNAVAILABLE',
            message: '当前播放器没有提供符合条件的直接媒体地址。',
            recoverable: false
          }
        };
      return {
        data: {
          videoId: details.videoId || expectedVideoId,
          canonicalUrl,
          items,
          count: items.length,
          truncated: matchingItems.length > maxResults
        },
        warnings: [
          '下载地址来自当前播放器且通常有时效；工具不会破解签名、合并分轨或绕过 DRM。'
        ]
      };
    }
  }
}


// 读取视频评论 — read. 自动加载评论区并分页读取评论；默认 20 条，单次最多 200
// 条。
async function youtube_get_video_comments(rawInput = {}) {
  const youtubeAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        ['www.youtube.com', 'm.youtube.com'].includes(url.hostname) &&
        (url.pathname === '/' ||
         (url.pathname === '/watch' &&
          /^[\w-]{6,20}$/.test(url.searchParams.get('v') ?? ''))),
    toolNames: (url) => url.pathname === '/' ?
        ['youtube_get_home_feed'] :
        [
          'youtube_get_video_download_urls', 'youtube_get_video_comments',
          'youtube_get_video_details', 'youtube_get_subtitle_file'
        ]
  };
  const routeUrl = new URL(location.href);
  if (!youtubeAdapter.matches(routeUrl) ||
      !youtubeAdapter.toolNames(routeUrl).includes(
          'youtube_get_video_comments'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported YouTube page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['limit', 'cursor', 'includeReplies'].includes(key)) &&
        (!('limit' in rawInput) ||
         (Number.isInteger(rawInput['limit']) && rawInput['limit'] >= 1 &&
          rawInput['limit'] <= 200)) &&
        (!('cursor' in rawInput) ||
         (((typeof rawInput['cursor'] === 'string' &&
            [...rawInput['cursor']].length <= 512) ||
           (rawInput['cursor'] === null)))) &&
        (!('includeReplies' in rawInput) ||
         (typeof rawInput['includeReplies'] === 'boolean'))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const pause = (milliseconds = 0) =>
        new Promise((resolve) => setTimeout(resolve, milliseconds));
    const parseCount = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*([KMB]|万|萬|亿|億)?/i);
      if (!match)
        return null;
      const base = Number(match[1]);
      if (!Number.isFinite(base))
        return null;
      const multipliers =
          {k: 1e3, m: 1e6, b: 1e9, '万': 1e4, '萬': 1e4, '亿': 1e8, '億': 1e8};
      return Math.round(
          base * (multipliers[(match[2] || '').toLowerCase()] || 1));
    };
    if (location.pathname !== '/watch')
      throw new Error('UNSUPPORTED_ROUTE: 该操作只在 YouTube 视频详情页可用。');
    const expectedVideoId = new URL(location.href).searchParams.get('v') || '';
    const normalizePlayer = (entry) => {
      if (typeof entry !== 'string')
        return entry;
      try {
        return JSON.parse(entry);
      } catch {
        return null;
      }
    };
    const playerCandidates = [
      win.ytInitialPlayerResponse,
      win.ytplayer?.config?.args?.raw_player_response,
      document.querySelector('ytd-watch-flexy')?.playerData,
      document.querySelector('ytd-watch-flexy')?.data?.playerData
    ].map(normalizePlayer);
    const player =
        playerCandidates.find(
            (entry) => entry?.videoDetails?.videoId === expectedVideoId) ||
        playerCandidates.find((entry) => entry?.videoDetails) || {};
    const microformat = player.microformat?.playerMicroformatRenderer || {};
    const canonicalUrl =
        `${location.origin}/watch?v=${encodeURIComponent(expectedVideoId)}`;
    {
      const limit = Math.min(200, Math.max(1, Number(input.limit ?? 20)));
      const cursor = input.cursor == null    ? 0 :
          /^\d+$/.test(String(input.cursor)) ? Number(input.cursor) :
                                               -1;
      if (!Number.isSafeInteger(cursor) || cursor < 0 || cursor > 1000000)
        throw new Error(
            'VALIDATION_ERROR: cursor 必须是 0–1000000 的整数字符串。');
      const includeReplies = input.includeReplies === true;
      const originalY = window.scrollY;
      const commentMap = new Map();
      const commentFromNode = (node, parentId = null, repliesNode = node) => {
        const authorNode = node.querySelector(
            '#author-text, a[href^="/@"], a[href^="/channel/"]');
        const contentNode = node.querySelector(
            '#content-text, yt-attributed-string#content-text');
        const permalink = node.querySelector(
            '#published-time-text a[href*="lc="], a[href*="lc="]');
        const likeText = clean(
            node.querySelector('#vote-count-middle, #like-count')?.textContent);
        const replyButton = repliesNode.querySelector(
            '#more-replies, #more-replies-sub-thread');
        const replyText = clean(replyButton?.textContent);
        let id = '';
        try {
          id = new URL(permalink?.href || '', location.href)
                   .searchParams.get('lc') ||
              '';
        } catch {
          id = '';
        }
        id ||= clean(
            node.data?.commentId ||
            node.data?.comment?.commentRenderer?.commentId);
        const content = clean(contentNode?.textContent);
        if (!content)
          return null;
        id ||=
            `${clean(authorNode?.textContent)}\u0000${content.slice(0, 200)}`;
        return {
          id,
          parentId,
          author: {
            name: clean(authorNode?.textContent) || '未知用户',
            profileUrl: absolute(authorNode?.href) || null
          },
          content,
          publishedText:
              clean(node.querySelector('#published-time-text')?.textContent) ||
              null,
          likeCount: parseCount(likeText) || 0,
          replyCount: replyButton ? parseCount(replyText) : 0,
          pinned: node.hasAttribute('pinned') ||
              /^Pinned by|^置顶/i.test(clean(node.textContent)),
          sourceUrl: permalink ? absolute(permalink.href) : canonicalUrl
        };
      };
      const collectComments = () => {
        const threads = Array.from(
            document.querySelectorAll('ytd-comment-thread-renderer'));
        const roots = threads.length ?
            threads :
            Array.from(document.querySelectorAll('ytd-comment-view-model'));
        for (const thread of roots) {
          const rootNode = thread.matches('ytd-comment-view-model') ?
              thread :
              thread.querySelector(
                  ':scope > ytd-comment-view-model, #comment') ||
                  (thread.querySelector('#content-text') ? thread : null);
          if (!rootNode)
            continue;
          const root = commentFromNode(rootNode, null, thread);
          if (root && !commentMap.has(root.id))
            commentMap.set(root.id, root);
          if (includeReplies && root) {
            const replies = Array.from(thread.querySelectorAll(
                'ytd-comment-replies-renderer ytd-comment-view-model'));
            for (const replyNode of replies) {
              const reply = commentFromNode(replyNode, root.id);
              if (reply && !commentMap.has(reply.id))
                commentMap.set(reply.id, reply);
            }
          }
        }
      };
      collectComments();
      if (!commentMap.size) {
        const commentsRoot = document.querySelector('#comments');
        if (commentsRoot && typeof commentsRoot.scrollIntoView === 'function')
          commentsRoot.scrollIntoView({block: 'start', behavior: 'auto'});
        else
          window.scrollTo({
            top: Math.max(1000, document.documentElement.scrollHeight * 0.45),
            behavior: 'auto'
          });
        for (let attempt = 0; attempt < 40 && !commentMap.size; attempt += 1) {
          await pause(200);
          collectComments();
        }
      }
      const targetCount = cursor + limit + 1;
      const maxScrolls =
          Math.min(20, Math.max(2, Math.ceil(targetCount / 20) + 2));
      let scrolls = 0;
      let idle = 0;
      while (commentMap.size < targetCount && scrolls < maxScrolls &&
             idle < 3) {
        const before = commentMap.size;
        window.scrollTo(
            {top: document.documentElement.scrollHeight, behavior: 'auto'});
        await pause(500);
        collectComments();
        scrolls += 1;
        idle = commentMap.size === before ? idle + 1 : 0;
      }
      const loaded = Array.from(commentMap.values());
      const items = loaded.slice(cursor, cursor + limit);
      const possiblyMore = cursor + items.length < loaded.length ||
          (items.length === limit && idle < 3);
      window.scrollTo({top: originalY, behavior: 'auto'});
      await pause(80);
      return {
        data: {
          items,
          count: items.length,
          totalLoaded: loaded.length,
          nextCursor: possiblyMore ? String(cursor + items.length) : null,
          hasMore: possiblyMore,
          truncated: possiblyMore
        },
        warnings: [
          '评论按 YouTube 当前排序读取；只包含本次调用中页面实际加载的内容。',
          ...(includeReplies ?
                  ['只返回页面已经展开的回复，不会点击“查看更多回复”。'] :
                  [])
        ]
      };
    }
  }
}


// 读取视频详情 — read.
// 读取标题、完整描述、频道、时长、观看数、点赞数、发布时间、分类、封面和字幕轨等信息。
async function youtube_get_video_details(rawInput = {}) {
  const youtubeAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        ['www.youtube.com', 'm.youtube.com'].includes(url.hostname) &&
        (url.pathname === '/' ||
         (url.pathname === '/watch' &&
          /^[\w-]{6,20}$/.test(url.searchParams.get('v') ?? ''))),
    toolNames: (url) => url.pathname === '/' ?
        ['youtube_get_home_feed'] :
        [
          'youtube_get_video_download_urls', 'youtube_get_video_comments',
          'youtube_get_video_details', 'youtube_get_subtitle_file'
        ]
  };
  const routeUrl = new URL(location.href);
  if (!youtubeAdapter.matches(routeUrl) ||
      !youtubeAdapter.toolNames(routeUrl).includes('youtube_get_video_details'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported YouTube page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(key => [].includes(key))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const win = globalThis;
  const meta = (name) =>
      document.querySelector(`meta[property="${name}"],meta[name="${name}"]`)
          ?.content?.trim() ||
      '';
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const duration = (value) => {
    const seconds = Number(value);
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
  };
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const runsText = (value) => clean(
        value?.simpleText || value?.content ||
        value?.runs?.map((entry) => entry.text).join('') || '');
    const parseCount = (value) => {
      const normalized = clean(value).replace(/,/g, '');
      const match = normalized.match(/([\d.]+)\s*([KMB]|万|萬|亿|億)?/i);
      if (!match)
        return null;
      const base = Number(match[1]);
      if (!Number.isFinite(base))
        return null;
      const multipliers =
          {k: 1e3, m: 1e6, b: 1e9, '万': 1e4, '萬': 1e4, '亿': 1e8, '億': 1e8};
      return Math.round(
          base * (multipliers[(match[2] || '').toLowerCase()] || 1));
    };
    if (location.pathname !== '/watch')
      throw new Error('UNSUPPORTED_ROUTE: 该操作只在 YouTube 视频详情页可用。');
    const expectedVideoId = new URL(location.href).searchParams.get('v') || '';
    const normalizePlayer = (entry) => {
      if (typeof entry !== 'string')
        return entry;
      try {
        return JSON.parse(entry);
      } catch {
        return null;
      }
    };
    const playerCandidates = [
      win.ytInitialPlayerResponse,
      win.ytplayer?.config?.args?.raw_player_response,
      document.querySelector('ytd-watch-flexy')?.playerData,
      document.querySelector('ytd-watch-flexy')?.data?.playerData
    ].map(normalizePlayer);
    const player =
        playerCandidates.find(
            (entry) => entry?.videoDetails?.videoId === expectedVideoId) ||
        playerCandidates.find((entry) => entry?.videoDetails) || {};
    const details = player.videoDetails || {};
    const microformat = player.microformat?.playerMicroformatRenderer || {};
    const streaming = player.streamingData || {};
    const rawFormats =
        [...(streaming.formats || []), ...(streaming.adaptiveFormats || [])];
    const rawTracks =
        player.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
    const trackSummary = (entry) => ({
      language: clean(entry.languageCode) || 'unknown',
      label: runsText(entry.name) || clean(entry.languageCode) || 'unknown',
      kind: clean(entry.kind) || 'standard',
      autoGenerated: entry.kind === 'asr',
      translatable: entry.isTranslatable === true
    });
    const subtitleTracks = rawTracks.map(trackSummary);
    const canonicalUrl =
        `${location.origin}/watch?v=${encodeURIComponent(expectedVideoId)}`;
    {
      const thumbnails = (microformat.thumbnail?.thumbnails ||
                          details.thumbnail?.thumbnails || [])
                             .map((entry) => ({
                                    url: absolute(entry.url),
                                    width: Number(entry.width) || null,
                                    height: Number(entry.height) || null
                                  }))
                             .filter((entry) => entry.url);
      const subscriberText =
          clean(document.querySelector('#owner-sub-count, #subscriber-count')
                    ?.textContent) ||
          null;
      return {
        data: {
          id: details.videoId || expectedVideoId,
          canonicalUrl,
          title: details.title || runsText(microformat.title) ||
              meta('og:title') || document.title,
          description: details.shortDescription ||
              runsText(microformat.description) || meta('description') || '',
          channel: {
            id: details.channelId || microformat.externalChannelId || null,
            name: details.author || microformat.ownerChannelName ||
                text(['#channel-name', 'ytd-channel-name']) || null,
            profileUrl: absolute(microformat.ownerProfileUrl) || null,
            subscriberText
          },
          durationSeconds: duration(
              details.lengthSeconds || microformat.lengthSeconds ||
              document.querySelector('video')?.duration),
          viewCount: parseCount(details.viewCount || microformat.viewCount),
          likeCount: parseCount(
              microformat.likeCount ||
              document
                  .querySelector(
                      '#segmented-like-button button, like-button-view-model button')
                  ?.getAttribute('aria-label')),
          publishDate: microformat.publishDate || null,
          uploadDate: microformat.uploadDate || null,
          category: microformat.category || null,
          keywords: Array.isArray(details.keywords) ?
              details.keywords.slice(0, 100) :
              [],
          thumbnails,
          flags: {
            allowRatings: details.allowRatings !== false,
            isLive: details.isLiveContent === true,
            isPrivate: details.isPrivate === true,
            isUnlisted: microformat.isUnlisted === true,
            isFamilySafe: microformat.isFamilySafe ?? null
          },
          subtitleTracks,
          formats: {
            total: rawFormats.length,
            direct: rawFormats.filter((entry) => Boolean(entry.url)).length,
            muxed:
                rawFormats
                    .filter(
                        (entry) => Boolean(entry.url) &&
                            String(entry.mimeType).startsWith('video/') &&
                            Boolean(entry.audioQuality || entry.audioChannels))
                    .length
          }
        }
      };
    }
  }
}


// 获取字幕文件 — export. 下载当前视频已有字幕；默认选择第一条字幕并导出为 SRT。
async function youtube_get_subtitle_file(rawInput = {}) {
  const youtubeAdapter = {
    matches: (url) => url.protocol === 'https:' &&
        ['www.youtube.com', 'm.youtube.com'].includes(url.hostname) &&
        (url.pathname === '/' ||
         (url.pathname === '/watch' &&
          /^[\w-]{6,20}$/.test(url.searchParams.get('v') ?? ''))),
    toolNames: (url) => url.pathname === '/' ?
        ['youtube_get_home_feed'] :
        [
          'youtube_get_video_download_urls', 'youtube_get_video_comments',
          'youtube_get_video_details', 'youtube_get_subtitle_file'
        ]
  };
  const routeUrl = new URL(location.href);
  if (!youtubeAdapter.matches(routeUrl) ||
      !youtubeAdapter.toolNames(routeUrl).includes('youtube_get_subtitle_file'))
    throw new Error(
        'UNSUPPORTED_ROUTE: Open a supported YouTube page for this recipe.');
  if (!(typeof rawInput === 'object' && rawInput !== null &&
        !Array.isArray(rawInput) &&
        Object.keys(rawInput).every(
            key => ['language', 'format'].includes(key)) &&
        (!('language' in rawInput) ||
         (typeof rawInput['language'] === 'string' &&
          [...rawInput['language']].length >= 1 &&
          [...rawInput['language']].length <= 32)) &&
        (!('format' in rawInput) ||
         (typeof rawInput['format'] === 'string' &&
          ['srt', 'vtt', 'json'].includes(rawInput['format'])))))
    throw new Error(
        'VALIDATION_ERROR: Inputs do not match the documented recipe contract.');
  const input = (rawInput && typeof rawInput === 'object' ? rawInput : {});
  const win = globalThis;
  const meta = (name) =>
      document.querySelector(`meta[property="${name}"],meta[name="${name}"]`)
          ?.content?.trim() ||
      '';
  const text = (selectors) => {
    for (const selector of selectors) {
      const value = document.querySelector(selector)?.textContent?.trim();
      if (value)
        return value;
    }
    return '';
  };
  const absolute = (value) => {
    const raw = String(value ?? '').trim();
    if (!raw)
      return '';
    try {
      return new URL(raw, location.href).href;
    } catch {
      return '';
    }
  };
  const safeTitle = (value, fallback) =>
      String(value || fallback).trim().slice(0, 120);
  const authBlock = text([
    '.login-container', '.login-mask', '[class*="captcha"]', '[class*="verify"]'
  ]);
  if (authBlock && /登录|验证码|verify|sign in/i.test(authBlock))
    return {
      data: null,
      error: {
        code: /验证码|verify/i.test(authBlock) ? 'PERMISSION_DENIED' :
                                                    'AUTH_REQUIRED',
        message: authBlock.slice(0, 180),
        recoverable: true
      }
    };
  const pageError = text([
    '#error-screen', '.error-container', '[class*="error-page"]',
    '[class*="exception"]'
  ]);
  if (/频繁|too many requests|rate limit|稍后再试/i.test(pageError))
    return {
      data: null,
      error: {
        code: 'RATE_LIMITED',
        message: pageError.slice(0, 180),
        recoverable: true
      }
    };
  if (/已删除|不存在|private video|video unavailable|内容无法查看/i
          .test(pageError))
    return {
      data: null,
      error: {
        code: 'CONTENT_UNAVAILABLE',
        message: pageError.slice(0, 180),
        recoverable: false
      }
    };
  {
    const clean = (value) => String(value ?? '')
                                 .replace(/[\u200B-\u200F\u2060\uFEFF]/g, '')
                                 .replace(/\s+/g, ' ')
                                 .trim();
    const runsText = (value) => clean(
        value?.simpleText || value?.content ||
        value?.runs?.map((entry) => entry.text).join('') || '');
    if (location.pathname !== '/watch')
      throw new Error('UNSUPPORTED_ROUTE: 该操作只在 YouTube 视频详情页可用。');
    const expectedVideoId = new URL(location.href).searchParams.get('v') || '';
    const normalizePlayer = (entry) => {
      if (typeof entry !== 'string')
        return entry;
      try {
        return JSON.parse(entry);
      } catch {
        return null;
      }
    };
    const playerCandidates = [
      win.ytInitialPlayerResponse,
      win.ytplayer?.config?.args?.raw_player_response,
      document.querySelector('ytd-watch-flexy')?.playerData,
      document.querySelector('ytd-watch-flexy')?.data?.playerData
    ].map(normalizePlayer);
    const player =
        playerCandidates.find(
            (entry) => entry?.videoDetails?.videoId === expectedVideoId) ||
        playerCandidates.find((entry) => entry?.videoDetails) || {};
    const details = player.videoDetails || {};
    const microformat = player.microformat?.playerMicroformatRenderer || {};
    const rawTracks =
        player.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
    const trackSummary = (entry) => ({
      language: clean(entry.languageCode) || 'unknown',
      label: runsText(entry.name) || clean(entry.languageCode) || 'unknown',
      kind: clean(entry.kind) || 'standard',
      autoGenerated: entry.kind === 'asr',
      translatable: entry.isTranslatable === true
    });
    const subtitleTracks = rawTracks.map(trackSummary);
    {
      const requested = clean(input.language);
      const track = rawTracks.find(
                        (entry) => clean(entry.languageCode).toLowerCase() ===
                                requested.toLowerCase() ||
                            runsText(entry.name).toLowerCase() ===
                                requested.toLowerCase()) ||
          (!requested ? rawTracks[0] : null);
      if (!track?.baseUrl)
        return {
          data: {available: subtitleTracks},
          error: {
            code: 'CONTENT_UNAVAILABLE',
            message: requested ? '当前视频没有请求的字幕轨。' :
                                 '当前视频没有可用字幕轨。',
            recoverable: false
          }
        };
      const format = clean(input.format || 'srt');
      const subtitleUrl = new URL(absolute(track.baseUrl));
      subtitleUrl.searchParams.set('fmt', 'json3');
      const language = clean(track.languageCode) || 'unknown';
      const mimeType = format === 'json' ? 'application/json' :
          format === 'vtt'               ? 'text/vtt' :
                                           'application/x-subrip';
      return {
        data: {
          videoId: details.videoId || expectedVideoId,
          selected: trackSummary(track),
          format,
          available: subtitleTracks
        },
        assets: [{
          url: subtitleUrl.href,
          filename:
              `${safeTitle(details.title || meta('og:title'), 'youtube')}-${
                  language}.${format}`,
          mimeType,
          sourceOrigin: location.origin,
          transform: {type: 'subtitle', format}
        }]
      };
    }
  }
}
