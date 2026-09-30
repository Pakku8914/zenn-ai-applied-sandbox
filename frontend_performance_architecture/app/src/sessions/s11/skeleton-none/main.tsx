import { mount } from '../mount';
import { SkeletonCatalog } from '../SkeletonCatalog';

// Bad：届くまで何も描かない
mount(<SkeletonCatalog mode="none" />);
