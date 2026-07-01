import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';

const thoughts = defineCollection({
	loader: glob({ pattern: '**/*.md', base: './src/content/thoughts' }),
});

export const collections = { thoughts };
