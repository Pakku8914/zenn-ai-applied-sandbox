import { mountCampaignCatalog } from '../CampaignCatalog';
import { reportWebVitals } from '../../../vitals';

// Good：バナーの高さを最初から確保しておき、届いたら中身だけを入れる
mountCampaignCatalog('reserved');
reportWebVitals();
