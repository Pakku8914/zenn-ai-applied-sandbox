import { mountCampaignCatalog } from '../CampaignCatalog';
import { reportWebVitals } from '../../../vitals';

// Bad：バナーの文言が届いてから、一覧の上に差し込む
mountCampaignCatalog('late');
reportWebVitals();
