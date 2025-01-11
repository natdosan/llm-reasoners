import os
import openai
import numpy as np
from typing import Optional, Union, Literal
import time
import requests
from reasoners.base import LanguageModel, GenerateOutput
from openai import OpenAI
import sglang as sgl
from sglang.api import set_default_backend
from sglang import RuntimeEndpoint, function, gen

PROMPT_TEMPLATE_ANSWER = 'Your response need to be ended with "So the answer is"\n\n'
PROMPT_TEMPLATE_CONTINUE = "Please continue to answer the last question, following the format of previous examples. Don't say any other words.\n\n"

class SGLangModel(LanguageModel):
    def __init__(
        self,
        model: str,
        max_tokens: int = 2048,
        temperature=0.0,
        additional_prompt=None,
        is_instruct_model: bool = False,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.additional_prompt = additional_prompt
        self.is_instruct_model = is_instruct_model
        self.__init_client__()

    def __init_client__(self):
        self.client = OpenAI(
            base_url=os.getenv("SGLANG_API_URL", None),
        )

    def generate(
        self,
        prompt: Optional[Union[str, list[str]]],
        max_tokens: int = None,
        top_p: float = 1.0,
        num_return_sequences: int = 1,
        rate_limit_per_min: Optional[int] = 20,
        stop: Optional[str] = None,
        logprobs: Optional[int] = None,
        temperature=None,
        additional_prompt=None,
        retry=64,
        **kwargs,
    ) -> GenerateOutput:

        max_tokens = self.max_tokens if max_tokens is None else max_tokens
        temperature = self.temperature if temperature is None else temperature
        logprobs = 0 if logprobs is None else logprobs
        if isinstance(prompt, list):
            assert len(prompt) == 1 
            prompt = prompt[0]
        if additional_prompt is None and self.additional_prompt is not None:
            additional_prompt = self.additional_prompt
        elif additional_prompt is not None and self.additional_prompt is not None:
            print("Warning: additional_prompt set in constructor is overridden.")
        if additional_prompt == "ANSWER":
            prompt = PROMPT_TEMPLATE_ANSWER + prompt
        elif additional_prompt == "CONTINUE":
            prompt = PROMPT_TEMPLATE_CONTINUE + prompt

        is_instruct_model = self.is_instruct_model
        if not is_instruct_model:
            # Recheck if the model is an instruct model with model name
            model_name = self.model.lower()
            if ("instruct" in model_name):
                is_instruct_model = True

        for i in range(1, retry + 1):
            try:
                # sleep several seconds to avoid rate limit
                if rate_limit_per_min is not None:
                    time.sleep(60 / rate_limit_per_min)
                if is_instruct_model:
                    messages = [{"role": "user", "content": prompt}]
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        n=num_return_sequences,
                        stop=stop,
                        logprobs=logprobs,
                    )
                    return GenerateOutput(
                        text=[choice.message.content for choice in response.choices],
                        log_prob=[token.logprob for token in response.choices[0].logprobs.content],
                    )
                else:
                    response = self.client.completions.create(
                        model=self.model,
                        prompt=prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        n=num_return_sequences,
                        stop=stop,
                        logprobs=logprobs,
                        **kwargs,
                    )
                    return GenerateOutput(
                        text=[choice.text for choice in response.choices],
                        log_prob=[choice.logprobs.token_logprobs for choice in response.choices],
                    )

            except Exception as e:
                print(f"An Error Occured: {e}, sleeping for {i} seconds")
                time.sleep(i)

        # after 64 tries, still no luck
        raise RuntimeError(
            "CompletionModel failed to generate output, even after 64 tries"
        )

    def get_next_token_logits(
        self,
        prompt: Union[str, list[str]],
        candidates: Union[list[str], list[list[str]]],
        **kwargs,
    ) -> list[np.ndarray]:
        raise NotImplementedError(
            "CompletionModel does not support get_next_token_logits"
        )

    def get_loglikelihood(self, prefix: str, contents: list[str], **kwargs) -> np.ndarray:
        actions = []
        for c in contents:
            if c.startswith(prefix):
                action = c[len(prefix):].strip()  # Remove the prefix and strip spaces
                actions.append(action)
            else:
                raise ValueError(f"'{prefix}' is not a prefix of '{c}'")
        
        base_url=os.getenv("SGLANG_API_URL", None)
        url = base_url.split("/", 3)[:3]
        url = "/".join(url)
        set_default_backend(RuntimeEndpoint(url))

        @sgl.function
        def helper(s):
            s += prefix + sgl.gen("logprob", choices=actions)

        state = helper.run()
        meta_info = state.get_meta_info("logprob")
        return np.array(meta_info['normalized_prompt_logprobs'])
        
        

if __name__ == "__main__":
    model = OpenAIModel(
        model="meta-llama/Llama-3.1-8B-Instruct",
        is_instruct_model=True,
    )
    print(model.generate(["How to go to Shanghai from Beijing?"]))
